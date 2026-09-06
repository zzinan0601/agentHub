"""동시 호출 검사 - 사용 중 표시 / 중단 / 끊겨도 저장.

폐쇄망의 로컬 모델은 한 응답에 몇 분이 걸린다. 그 사이에 무슨 일이 생겨도
**이미 한 일이 사라지지 않는 것**이 이 검사들의 목적이다.

    python scripts/test_concurrency.py

느린 에이전트가 있어야 겹치는 순간을 만들 수 있어, 검사가 스스로
`agents/slow` 를 띄웠다가 끝나면 정리한다.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("CORE_URL", "http://localhost:8000")
SLOW_PORT = 9099
SLOW_ID = "zz-slow"

ok_count = 0
fail_count = 0


def check(label: str, passed: bool, detail: str = "") -> None:
    global ok_count, fail_count
    if passed:
        ok_count += 1
        print(f"  [OK] {label}")
    else:
        fail_count += 1
        print(f"  [XX] {label}  {detail}")


# ---------------------------------------------------------------------------
# 느린 에이전트를 잠깐 띄운다 (계약은 템플릿이 지켜주므로 agent.py 만 쓰면 된다)
# ---------------------------------------------------------------------------

SLOW_AGENT = '''"""검사용 느린 에이전트. 겹치는 순간을 만들려고 일부러 오래 끈다."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from contract import Event, InvokeRequest, result, status


async def run(req: InvokeRequest) -> AsyncIterator[Event]:
    yield status("느리게 일하는 중")
    for i in range(30):
        await asyncio.sleep(1)
        yield status(f"{i + 1}초째")
    yield result("## 느린 결과\\n\\n끝났습니다.")
'''

SLOW_MANIFEST = {
    "id": SLOW_ID,
    "name": "느린 검사용",
    "description": "동시 호출 검사에만 쓰는 느린 에이전트. 30초를 끈다.",
    "owner": "검사",
    "tags": ["검사"],
    "examples": ["느리게 해줘"],
}


def install_slow_agent() -> Path:
    """agent_template 을 복사해 느린 에이전트를 만든다."""
    d = ROOT / "agents" / "zz-slow"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("main.py", "contract.py", "llm.py", "files.py"):
        (d / name).write_bytes((ROOT / "agent_template" / name).read_bytes())
    (d / "agent.py").write_text(SLOW_AGENT, encoding="utf-8")
    (d / "manifest.yaml").write_text(
        yaml.safe_dump(SLOW_MANIFEST, allow_unicode=True), encoding="utf-8"
    )
    return d


# 검사가 끝나면 원래 파일을 글자 그대로 되돌리기 위해 원문을 들고 있는다.
# yaml 로 읽었다가 다시 쓰면 주석이 통째로 사라진다. registry.yaml 의 주석에는
# 포트 규칙 같은 설명이 들어 있어 잃으면 안 된다.
_REGISTRY = ROOT / "registry.yaml"
_REGISTRY_ORIGINAL = _REGISTRY.read_text(encoding="utf-8")


def register(add: bool) -> None:
    """registry.yaml 에 느린 에이전트를 넣거나 뺀다. 코어가 30초 안에 알아챈다."""
    if add:
        entry = f"\n  - id: {SLOW_ID}\n    url: http://localhost:{SLOW_PORT}\n"
        _REGISTRY.write_text(_REGISTRY_ORIGINAL.rstrip() + entry, encoding="utf-8")
    else:
        _REGISTRY.write_text(_REGISTRY_ORIGINAL, encoding="utf-8")  # 원문 그대로 복구


def wait_for(fn, timeout: float = 20.0, step: float = 0.4) -> bool:
    """조건이 참이 될 때까지 기다린다. 폴링 주기가 있어 즉시 반영되지 않는다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(step)
    return False


# ---------------------------------------------------------------------------


def answers(c: httpx.Client, room_id: int) -> list[dict]:
    """답변만 센다. 질문은 보내는 즉시 저장되므로 전체 개수로 세면 안 된다."""
    rows = c.get(f"/api/rooms/{room_id}/messages").json()
    return [m for m in rows if m["role"] in ("assistant", "schedule")]


def agent_state(c: httpx.Client, agent_id: str) -> dict:
    for a in c.get("/api/agents").json():
        if a["id"] == agent_id:
            return a
    return {}


async def run_checks(c: httpx.Client, room_id: int) -> None:
    """스트리밍을 실제로 열어야 확인되는 것들."""
    global ok_count, fail_count

    async with httpx.AsyncClient(base_url=BASE, cookies=c.cookies, timeout=60.0) as ac:

        # --- 1. 호출 중에 busy 로 보이는지 ---------------------------------
        async def ask(msg: str):
            async with ac.stream(
                "POST", "/api/chat", json={"room_id": room_id, "message": msg}
            ) as res:
                async for _ in res.aiter_lines():
                    pass

        task = asyncio.create_task(ask("느리게 해줘"))
        await asyncio.sleep(3)

        state = agent_state(c, SLOW_ID)
        check("호출 중이면 busy 로 보인다", state.get("busy") is True, str(state))
        check("누가 쓰는지 이름이 실린다", bool(state.get("busy_by")), str(state.get("busy_by")))
        check("몇 초째인지 센다", state.get("busy_seconds", 0) >= 1, str(state.get("busy_seconds")))

        # --- 2. 같은 방에 두 번째 실행 -> 409 ------------------------------
        r = c.post("/api/chat", json={"room_id": room_id, "message": "또"})
        check("같은 방에 두 번째 실행은 거부", r.status_code == 409, f"-> {r.status_code}")

        # --- 3. 다른 방에서 같은 에이전트 -> 409 ---------------------------
        other = c.post("/api/rooms", json={"title": "동시호출 점검 B"}).json()
        c.patch(f"/api/rooms/{other['id']}", json={"agents": [SLOW_ID]})
        r = c.post("/api/chat", json={"room_id": other["id"], "message": "나도"})
        check("다른 방이라도 같은 에이전트면 거부", r.status_code == 409, f"-> {r.status_code}")
        check("거부 문구에 누가 쓰는지 나온다", "쓰는 중" in r.text, r.text[:140])
        c.delete(f"/api/rooms/{other['id']}")

        # --- 4. 중단 -------------------------------------------------------
        before = len(answers(c, room_id))
        r = c.delete(f"/api/rooms/{room_id}/run")
        check("중단 요청이 받아들여진다", r.json().get("cancelled") is True, r.text[:120])
        await asyncio.wait_for(task, timeout=15)

        check("중단하면 busy 가 풀린다",
              wait_for(lambda: not agent_state(c, SLOW_ID).get("busy"), 10))

        msgs = answers(c, room_id)
        check("중단해도 답이 남는다", len(msgs) > before, f"{before} -> {len(msgs)}")
        check("중단 표시가 붙는다", msgs[-1]["meta"].get("cancelled") is True,
              str(msgs[-1]["meta"])[:140])

        # --- 5. ★ 끊겨도 끝까지 돌고 저장되는지 -----------------------------
        before = len(answers(c, room_id))
        async with ac.stream(
            "POST", "/api/chat", json={"room_id": room_id, "message": "끊어볼게"}
        ) as res:
            async for _ in res.aiter_lines():
                break  # 첫 줄만 받고 그대로 끊는다 (탭 닫기와 같다)

        check("끊은 직후에도 서버는 계속 돈다",
              wait_for(lambda: agent_state(c, SLOW_ID).get("busy") is True, 5))

        # 느린 에이전트가 30초를 끈다. 끝나고 저장될 때까지 기다린다.
        saved = wait_for(lambda: len(answers(c, room_id)) > before, 60)
        check("★ 브라우저가 끊겨도 결과가 저장된다", saved, f"답변 {before}개에서 그대로")
        if saved:
            last = answers(c, room_id)[-1]
            check("저장된 것이 온전한 답이다", "끝났습니다" in last["content_md"],
                  last["content_md"][:80])
            check("중단이 아니라 정상 완료로 남는다", not last["meta"].get("cancelled"),
                  str(last["meta"])[:120])
        check("끝나면 busy 가 풀린다",
              wait_for(lambda: not agent_state(c, SLOW_ID).get("busy"), 10))


def main() -> int:
    print("\n느린 검사용 에이전트를 띄웁니다...")
    install_slow_agent()
    register(True)
    proc = subprocess.Popen(
        [str(ROOT / ".venv/Scripts/python"), "main.py"],
        cwd=str(ROOT / "agents" / "zz-slow"),
        env={**os.environ, "PORT": str(SLOW_PORT), "AGENT_PORT": str(SLOW_PORT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    c = httpx.Client(base_url=BASE, timeout=30.0)
    try:
        if not wait_for(
            lambda: httpx.get(f"http://localhost:{SLOW_PORT}/health").status_code == 200, 25
        ):
            print("  느린 에이전트를 띄우지 못했습니다.")
            return 1

        c.post("/api/auth/login", json={"username": "동시호출점검"}).raise_for_status()
        c.post("/api/agents/refresh")
        check("느린 에이전트가 목록에 온라인으로 뜬다",
              wait_for(lambda: agent_state(c, SLOW_ID).get("online") is True, 20))

        room = c.post("/api/rooms", json={"title": "동시호출 점검"}).json()
        c.patch(f"/api/rooms/{room['id']}", json={"agents": [SLOW_ID]})

        print()
        asyncio.run(run_checks(c, room["id"]))

        c.delete(f"/api/rooms/{room['id']}")
    finally:
        proc.terminate()
        register(False)
        c.post("/api/agents/refresh")
        c.close()
        import shutil

        shutil.rmtree(ROOT / "agents" / "zz-slow", ignore_errors=True)

    print(f"\n  {ok_count + fail_count}개 중 {ok_count}개 통과")
    return 1 if fail_count else 0


if __name__ == "__main__":
    print("\n동시 호출 검사")
    sys.exit(main())
