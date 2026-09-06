"""계약 자가검사 - 내 에이전트가 규약을 지키는지 확인한다.

에이전트를 띄운 상태에서 실행한다. 제출 전에 반드시 한 번 돌린다.

    python scripts/check_contract.py                  # registry.yaml 의 전체 에이전트
    python scripts/check_contract.py http://localhost:9001   # 특정 주소만
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.contract import CONTRACT_VERSION, Manifest  # noqa: E402

OK, NG = "OK  ", "실패"


class Check:
    """검사 결과 한 줄."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.lines: list[tuple[str, bool, str]] = []

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.lines.append((name, passed, detail))

    @property
    def passed(self) -> bool:
        return all(p for _, p, _ in self.lines)

    def report(self) -> None:
        print(f"\n=== {self.url} ===")
        for name, passed, detail in self.lines:
            mark = OK if passed else NG
            print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail else ""))


async def check_agent(url: str) -> Check:
    url = url.rstrip("/")
    check = Check(url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. manifest
        try:
            res = await client.get(f"{url}/manifest")
            res.raise_for_status()
            manifest = Manifest(**res.json())
            check.add("GET /manifest 응답", True)
            check.add(
                "계약 버전 일치",
                manifest.contract_version == CONTRACT_VERSION,
                f"에이전트 {manifest.contract_version} / 코어 {CONTRACT_VERSION}",
            )
            check.add(
                "description 이 채워져 있음",
                len(manifest.description.strip()) >= 20,
                "라우터 LLM 이 읽는 핵심 필드입니다. 구체적으로 쓰세요.",
            )
            check.add(
                "examples 가 1개 이상",
                len(manifest.examples) >= 1,
                "질문 예시가 있어야 라우팅이 정확해집니다.",
            )
        except Exception as exc:  # noqa: BLE001
            check.add("GET /manifest 응답", False, str(exc))
            return check

        # 2. health
        try:
            res = await client.get(f"{url}/health")
            res.raise_for_status()
            check.add("GET /health 응답", res.json().get("status") == "ok")
        except Exception as exc:  # noqa: BLE001
            check.add("GET /health 응답", False, str(exc))

        # 3. invoke 스트림
        # 코어가 내려주는 것과 같은 형태의 요청을 만든다. 모델은 .env 의 기본값을 쓴다.
        body = {
            "request_id": "contract-check",
            "room_id": 0,
            "query": "계약 검사용 질문입니다. 짧게 답해주세요.",
            "model": os.getenv("DEFAULT_MODEL", "gemma4:31b-cloud"),
            "stream": True,
        }

        events: list[dict] = []
        bad_lines = 0
        try:
            async with client.stream("POST", f"{url}/invoke", json=body) as res:
                res.raise_for_status()
                content_type = res.headers.get("content-type", "")
                check.add(
                    "Content-Type 이 application/x-ndjson",
                    "x-ndjson" in content_type,
                    content_type,
                )
                async for line in res.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        bad_lines += 1
        except Exception as exc:  # noqa: BLE001
            check.add("POST /invoke 스트림", False, str(exc))
            return check

        check.add("POST /invoke 스트림", True, f"이벤트 {len(events)}개")
        check.add("모든 줄이 JSON", bad_lines == 0, f"깨진 줄 {bad_lines}개")

        terminal = [e for e in events if e.get("type") in ("result", "error")]
        check.add("종료 이벤트가 정확히 1개", len(terminal) == 1, f"{len(terminal)}개")
        check.add(
            "종료 이벤트가 마지막 줄",
            bool(events) and events[-1].get("type") in ("result", "error"),
        )
        if terminal and terminal[0].get("type") == "result":
            markdown = terminal[0].get("markdown", "")
            check.add("result.markdown 이 비어있지 않음", bool(markdown.strip()))
            for att in terminal[0].get("attachments") or []:
                name = att.get("file", "")
                ok = name and "/" not in name and "\\" not in name and ".." not in name
                check.add(f"첨부 '{att.get('name')}' 파일명이 안전함", bool(ok), name)
                res = await client.get(f"{url}/files/{name}")
                check.add(f"첨부 '{att.get('name')}' 다운로드", res.status_code == 200)
        elif terminal:
            check.add(
                "result 로 끝남",
                False,
                f"error 로 끝났습니다: {terminal[0].get('message', '')[:120]}",
            )

    return check


async def main() -> int:
    if len(sys.argv) > 1:
        urls = sys.argv[1:]
    else:
        data = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8")) or {}
        urls = [a["url"] for a in data.get("agents", [])]
        if not urls:
            print("registry.yaml 에 에이전트가 없습니다.")
            return 1

    checks = await asyncio.gather(*(check_agent(u) for u in urls))
    for check in checks:
        check.report()

    failed = [c for c in checks if not c.passed]
    print(f"\n총 {len(checks)}개 중 {len(checks) - len(failed)}개 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
