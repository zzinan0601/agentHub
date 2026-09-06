"""파이프라인 검사 - 합치기 설정 / 순차 순서 / 단계별 계측.

폐쇄망의 로컬 모델은 한 번 부를 때마다 수십 초다. 그래서
  - 코어 LLM 을 언제 부르고 언제 안 부르는지
  - 순차의 실행 순서가 무엇으로 정해지는지
  - 어디서 시간을 쓰는지
가 눈에 보여야 한다. 그 셋을 확인한다.

    python scripts/test_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = os.environ.get("CORE_URL", "http://localhost:8000")

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


def saved_runs(c: httpx.Client, room_id: int) -> list[str]:
    """저장된 마지막 답변의 실제 호출 순서.

    runs 는 저장할 때 붙으므로 스트림의 result 이벤트에는 없다. 화면이 실행 트레이스에
    쓰는 것과 같은 값을 봐야 의미가 있다.
    """
    rows = c.get(f"/api/rooms/{room_id}/messages").json()
    answers = [m for m in rows if m["role"] in ("assistant", "schedule")]
    if not answers:
        return []
    return [r.get("agent_id") for r in (answers[-1]["meta"].get("runs") or [])]


def ask(c: httpx.Client, room_id: int, text: str) -> dict:
    """질문 하나를 끝까지 받아 필요한 것만 추린다."""
    out = {"per_agent": {}, "final": "", "core_deltas": 0, "plan": None, "meta": {}}
    with c.stream("POST", "/api/chat", json={"room_id": room_id, "message": text}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            e = json.loads(line)
            aid = e.get("agent_id")
            if e["type"] == "plan":
                out["plan"] = e
            elif e["type"] == "delta" and not aid:
                out["core_deltas"] += 1
            elif e["type"] == "result" and aid:
                out["per_agent"][aid] = e.get("markdown", "")
            elif e["type"] == "result" and not aid:
                out["final"] = e.get("markdown", "")
                out["meta"] = e.get("meta") or {}
    return out


def main() -> int:
    from core.config import settings

    c = httpx.Client(base_url=BASE, timeout=300.0)
    c.post("/api/auth/login", json={"username": "파이프라인점검"}).raise_for_status()
    room = c.post("/api/rooms", json={"title": "파이프라인 점검"}).json()
    rid = room["id"]

    # --- 병렬 --------------------------------------------------------------
    print(f"\n[병렬] REDUCE_MODE={settings.reduce_mode}")
    c.patch(f"/api/rooms/{rid}", json={"agents": ["echo", "summary"], "mode": "parallel"})
    r = ask(c, rid, "지점별 매출 알려줘")

    if settings.reduce_mode == "llm":
        check("합치기 모드에서는 코어 LLM 이 돈다", r["core_deltas"] > 0)
    else:
        check("붙이기 모드에서는 코어 LLM 을 부르지 않는다", r["core_deltas"] == 0,
              f"delta {r['core_deltas']}개")
        for aid, md in r["per_agent"].items():
            first = md.strip().split("\n")[0][:15]
            check(f"{aid} 의 결과가 최종에 남아 있다", first in r["final"], first)
        check("에이전트 이름이 제목으로 붙는다", r["final"].count("\n## ") + r["final"].startswith("## ") >= 2,
              r["final"][:60])

    # --- 순차: 순서가 지켜지는가 ---------------------------------------------
    print("\n[순차] 고른 순서대로 도는가")
    c.patch(f"/api/rooms/{rid}", json={"agents": ["summary", "echo"], "mode": "sequential"})
    saved = c.get(f"/api/rooms/{rid}").json()["agents"]
    check("고른 순서가 그대로 저장된다", saved == ["summary", "echo"], str(saved))

    # 새로 읽어도(=새로고침해도) 순서가 유지되어야 한다. 예전에는 여기서 뒤집혔다.
    again = c.get(f"/api/rooms/{rid}").json()["agents"]
    check("다시 읽어도 순서가 그대로다", again == ["summary", "echo"], str(again))

    r = ask(c, rid, "지점별 매출 알려줘")
    check("계획의 순서가 고른 순서와 같다", r["plan"]["agents"] == ["summary", "echo"],
          str(r["plan"]["agents"]))
    order = saved_runs(c, rid)
    check("실제 호출 순서도 같다", order == ["summary", "echo"], str(order))
    if settings.reduce_mode != "llm":
        check("순차도 코어 LLM 을 부르지 않는다", r["core_deltas"] == 0,
              f"delta {r['core_deltas']}개")
    # 순차라고 앞 단계를 버리면 안 된다. "매출 알려주고 요약해줘" 는 둘 다 원한 것이다.
    for aid, md in r["per_agent"].items():
        first = [ln for ln in md.strip().splitlines() if ln.strip()][0][:15]
        check(f"순차에서 {aid} 의 결과가 남는다", first in r["final"], first)

    # 순서를 뒤집으면 그대로 따라와야 한다
    c.patch(f"/api/rooms/{rid}", json={"agents": ["echo", "summary"], "mode": "sequential"})
    r = ask(c, rid, "지점별 매출 알려줘")
    order = saved_runs(c, rid)
    check("순서를 바꾸면 실행 순서도 바뀐다", order == ["echo", "summary"], str(order))

    # --- 계측 --------------------------------------------------------------
    print("\n[계측] 어디서 시간을 썼는가")
    t = r["meta"].get("timings") or {}
    check("timings 가 실린다", bool(t), str(t))
    check("에이전트 시간이 잡힌다", t.get("agents_ms", 0) > 0, str(t.get("agents_ms")))
    check("전체 시간이 잡힌다", t.get("total_ms", 0) > 0, str(t.get("total_ms")))
    check("직접 고른 질문은 라우팅 시간이 0", not t.get("route_ms"), str(t.get("route_ms")))

    # 자동 라우팅이면 route_ms 가 잡혀야 한다
    c.patch(f"/api/rooms/{rid}", json={"agents": []})
    r = ask(c, rid, "지점별 매출 알려줘")
    t = r["meta"].get("timings") or {}
    check("자동 라우팅이면 라우팅 시간이 잡힌다", t.get("route_ms", 0) > 0, str(t))

    # 잡담 -> 직접 답변
    r = ask(c, rid, "안녕? 오늘 기분 어때")
    t = r["meta"].get("timings") or {}
    check("직접 답변 시간이 잡힌다", t.get("direct_ms", 0) > 0, str(t))

    # Dashboard 가 코어 시간을 내려주는지
    recent = c.get("/api/insights?period=all").json()["recent"]
    check("Dashboard 최근 질문에 core_ms 가 실린다",
          any(q.get("core_ms", 0) > 0 for q in recent[:10]),
          str([q.get("core_ms") for q in recent[:5]]))

    c.delete(f"/api/rooms/{rid}")
    c.close()

    print(f"\n  {ok_count + fail_count}개 중 {ok_count}개 통과")
    return 1 if fail_count else 0


if __name__ == "__main__":
    print("\n파이프라인 검사")
    sys.exit(main())
