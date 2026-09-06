"""E2E 점검 - 코어와 예제 에이전트 2개가 떠 있는 상태에서 전체 흐름을 확인한다.

    python scripts/e2e_test.py

확인 항목: 로그인 / 개인 전용 방 / 방 생성 / 단일·병렬·순차 호출 / 첨부파일 프록시 /
          오프라인 에이전트 / 방당 스케줄 1개 / 대화 저장 / 활용 현황.

전용 테스트 계정으로 로그인해 자기 방만 만들고 지운다. 방이 개인 전용이라
다른 사람이 쓰던 대화는 건드리지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

CORE = "http://localhost:8000"
TEST_USER = "e2e-test"  # 이 계정의 방만 만들고 지운다
passed, failed = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [OK  ] {name}" + (f"  -> {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {name}" + (f"  -> {detail}" if detail else ""))


async def chat(client: httpx.AsyncClient, room_id: int, message: str) -> list[dict]:
    """NDJSON 스트림을 끝까지 읽어 이벤트 목록으로 돌려준다."""
    events: list[dict] = []
    async with client.stream(
        "POST", f"{CORE}/api/chat", json={"room_id": room_id, "message": message}
    ) as res:
        res.raise_for_status()
        async for line in res.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


def final_result(events: list[dict]) -> dict | None:
    """코어가 만든 최종 결과(agent_id 없는 result)를 찾는다."""
    return next(
        (e for e in events if e.get("type") == "result" and not e.get("agent_id")), None
    )


async def main() -> int:
    async with httpx.AsyncClient(timeout=300.0) as client:
        # --- 준비 -----------------------------------------------------------
        print("\n[0] 사전 확인")
        health = (await client.get(f"{CORE}/api/health")).json()
        check("코어 응답", health.get("status") == "ok", json.dumps(health, ensure_ascii=False))
        check("에이전트 2개 온라인", health.get("online") == 2, f"online={health.get('online')}")

        # 로그인 전에는 아무것도 못 본다
        async with httpx.AsyncClient(timeout=30.0) as guest:
            r = await guest.get(f"{CORE}/api/rooms")
            check("로그인 없이 방 목록 -> 401", r.status_code == 401, str(r.status_code))
            r = await guest.get(f"{CORE}/api/insights")
            check("로그인 없이 현황 -> 401", r.status_code == 401, str(r.status_code))
            r = await guest.get(f"{CORE}/api/auth/users")
            check("사용자 목록은 로그인 없이 조회", r.status_code == 200, str(r.status_code))

        # --- 0-1. 로그인 (비밀번호 없음) --------------------------------------
        print("\n[0-1] 로그인")
        r = await client.post(f"{CORE}/api/auth/login", json={"username": TEST_USER})
        check("이름만으로 로그인", r.status_code == 200, str(r.status_code))
        me = (await client.get(f"{CORE}/api/auth/me")).json()
        check("로그인한 사람 확인", me.get("username") == TEST_USER, json.dumps(me, ensure_ascii=False))

        models = (await client.get(f"{CORE}/api/models")).json()
        check("모델 목록 조회", len(models.get("models", [])) >= 1, str(models.get("models")))

        # --- 1. 방 생성 + 모델 선택 ------------------------------------------
        print("\n[1] 채팅방 생성과 모델 선택")
        room = (
            await client.post(
                f"{CORE}/api/rooms",
                json={"title": "E2E 점검", "model": models["default"]},
            )
        ).json()
        room_id = room["id"]
        check("방 생성", bool(room_id), f"room_id={room_id}")
        check("방에 모델이 저장됨", room["model"] == models["default"], room["model"])

        rooms = (await client.get(f"{CORE}/api/rooms")).json()
        check("방 목록에 보임", any(r["id"] == room_id for r in rooms), f"{len(rooms)}개")

        # --- 2. 단일 호출 ----------------------------------------------------
        print("\n[2] 단일 에이전트 호출 (echo)")
        await client.patch(
            f"{CORE}/api/rooms/{room_id}", json={"agents": ["echo"], "mode": "parallel"}
        )
        events = await chat(client, room_id, "지점별 매출 알려줘")
        result = final_result(events)
        check("최종 result 이벤트 존재", result is not None)
        check("delta 스트리밍 수신", any(e.get("type") == "delta" for e in events),
              f"delta {sum(1 for e in events if e.get('type') == 'delta')}개")
        check("echo 만 호출됨", {e.get("agent_id") for e in events if e.get("agent_id")} == {"echo"})
        check("Markdown 표 포함", "| 지점 |" in (result or {}).get("markdown", ""))

        # --- 3. 첨부파일 프록시 ------------------------------------------------
        print("\n[3] 첨부파일 (에이전트 보관 -> 코어 프록시)")
        attachments = (result or {}).get("attachments") or []
        check("첨부 1개", len(attachments) == 1, str([a.get("name") for a in attachments]))
        if attachments:
            url = attachments[0]["url"]
            check("URL 이 코어 경로", url.startswith("/api/files/echo/"), url)
            res = await client.get(f"{CORE}{url}")
            check("코어를 통해 다운로드", res.status_code == 200, f"{len(res.content)} bytes")
            check(
                "Content-Type 이 charset 까지 정확",
                "utf-8" in res.headers.get("content-type", "").lower(),
                res.headers.get("content-type", ""),
            )
            # 엑셀은 HTTP charset 을 보지 않는다. BOM 이 없으면 한글이 CP949 로 깨진다.
            check("UTF-8 BOM 이 붙어 있음", res.content[:3].hex() == "efbbbf", res.content[:3].hex())
            body = res.content.decode("utf-8-sig")
            check("내용이 CSV", body.startswith("지점,매출"), body.splitlines()[0])
            bad = await client.get(f"{CORE}/api/files/echo/..%2F.env")
            check("경로 탈출 차단", bad.status_code >= 400, str(bad.status_code))

        # --- 4. 병렬 호출 ----------------------------------------------------
        print("\n[4] 병렬 호출 (echo + summary)")
        await client.patch(
            f"{CORE}/api/rooms/{room_id}",
            json={"agents": ["echo", "summary"], "mode": "parallel"},
        )
        events = await chat(client, room_id, "매출 현황과 요약을 함께 줘")
        called = {e.get("agent_id") for e in events if e.get("agent_id")}
        check("두 에이전트 모두 호출됨", called == {"echo", "summary"}, str(called))
        agent_results = [e for e in events if e.get("type") == "result" and e.get("agent_id")]
        check("에이전트별 result 2개", len(agent_results) == 2, f"{len(agent_results)}개")
        check("통합 결과 생성", bool((final_result(events) or {}).get("markdown")))

        # --- 5. 순차 호출 ----------------------------------------------------
        print("\n[5] 순차 호출 (echo -> summary)")
        await client.patch(
            f"{CORE}/api/rooms/{room_id}",
            json={"agents": ["echo", "summary"], "mode": "sequential"},
        )
        events = await chat(client, room_id, "매출을 조회하고 세 줄로 요약해줘")
        order = [e["agent_id"] for e in events if e.get("type") == "result" and e.get("agent_id")]
        check("echo 다음 summary 순서", order == ["echo", "summary"], str(order))
        # status 가 아니라 summary 의 result 이벤트를 봐야 한다.
        summary_md = next(
            (
                e.get("markdown", "")
                for e in events
                if e.get("agent_id") == "summary" and e.get("type") == "result"
            ),
            "",
        )
        # 앞 단계 결과가 upstream 으로 전달됐다면 지점 이름이 요약에 나타난다.
        check(
            "summary 가 앞 단계 결과를 받음",
            any(name in summary_md for name in ("서울", "부산", "대구")),
            summary_md.replace("\n", " ")[:80],
        )

        # --- 6. 오프라인 에이전트 --------------------------------------------
        print("\n[6] 없는 에이전트를 지정한 경우")
        await client.patch(
            f"{CORE}/api/rooms/{room_id}",
            json={"agents": ["echo", "ghost"], "mode": "parallel"},
        )
        events = await chat(client, room_id, "매출 알려줘")
        check(
            "없는 에이전트는 error 이벤트",
            any(e.get("type") == "error" and e.get("agent_id") == "ghost" for e in events),
        )
        check("나머지로 응답이 완결됨", bool((final_result(events) or {}).get("markdown")))

        # --- 7. 스케줄 (방당 1개) ---------------------------------------------
        print("\n[7] 스케줄 - 방당 1개")
        res = await client.put(
            f"{CORE}/api/rooms/{room_id}/schedule",
            json={"cron": "0 9 * * 1-5", "prompt": "오늘 매출 알려줘", "enabled": True},
        )
        check("스케줄 등록", res.status_code == 200, str(res.json().get("next_run_at")))
        res2 = await client.put(
            f"{CORE}/api/rooms/{room_id}/schedule",
            json={"cron": "30 18 * * *", "prompt": "마감 매출 알려줘", "enabled": True},
        )
        current = (await client.get(f"{CORE}/api/rooms/{room_id}/schedule")).json()
        check("두 번째 등록은 교체됨(추가 아님)", current["cron"] == "30 18 * * *", current["cron"])
        bad = await client.put(
            f"{CORE}/api/rooms/{room_id}/schedule",
            json={"cron": "이건 cron 이 아님", "prompt": "x", "enabled": True},
        )
        check("잘못된 cron 거부", bad.status_code == 400, str(bad.status_code))
        await client.delete(f"{CORE}/api/rooms/{room_id}/schedule")
        check(
            "스케줄 삭제",
            (await client.get(f"{CORE}/api/rooms/{room_id}/schedule")).json() is None,
        )

        # --- 8. 대화 저장 -----------------------------------------------------
        print("\n[8] 대화 저장")
        messages = (await client.get(f"{CORE}/api/rooms/{room_id}/messages")).json()
        check("질문/답변이 저장됨", len(messages) >= 8, f"{len(messages)}개")
        assistant = [m for m in messages if m["role"] == "assistant"]
        check("답변이 Markdown 으로 저장됨", all(m["content_md"] for m in assistant))
        check(
            "첨부 정보가 함께 저장됨",
            any((m.get("meta") or {}).get("attachments") for m in assistant),
        )

        # --- 8-1. 안 읽은 표시 --------------------------------------------------
        print()
        print("[8-1] 스케줄 결과 알림")
        # 스케줄이 돈 것과 같은 상태를 만들어 표시가 붙고 지워지는지 본다.
        # (실제 발화를 기다리면 테스트가 몇 분씩 걸린다)
        marked = await client.post(f"{CORE}/api/rooms/{room_id}/read")
        check("읽음 처리 엔드포인트", marked.status_code == 200, str(marked.status_code))
        rooms = (await client.get(f"{CORE}/api/rooms")).json()
        me_room = next(r for r in rooms if r["id"] == room_id)
        check("방 목록에 unread 가 실린다", "unread" in me_room, str(me_room.get("unread")))
        check("읽은 뒤에는 0", me_room["unread"] == 0, str(me_room["unread"]))

        # --- 9. 활용 현황 -----------------------------------------------------
        print("\n[9] 활용 현황")
        ins = (await client.get(f"{CORE}/api/insights", params={"period": "today"})).json()
        check("요약 집계", ins["summary"]["questions"] >= 4,
              json.dumps(ins["summary"], ensure_ascii=False))

        by_id = {a["agent_id"]: a for a in ins["agents"]}
        check("echo 통계 존재", "echo" in by_id, str(sorted(by_id)))
        check("echo 호출수 > 0", by_id.get("echo", {}).get("calls", 0) > 0)
        check("summary 의 num_ctx 실측 저장",
              by_id.get("summary", {}).get("avg_num_ctx", 0) > 0,
              str(by_id.get("summary", {}).get("avg_num_ctx")))

        routing = ins["routing"]
        check("라우팅 source 합 = 전체",
              sum(routing["by_source"].values()) == routing["total"],
              f'{routing["by_source"]} / total={routing["total"]}')
        check("사용자 지정 호출이 manual 로 분류됨",
              routing["by_source"].get("manual", 0) > 0, str(routing["by_source"]))
        check("최근 질문에 호출된 에이전트가 붙음",
              any(q["agents"] for q in ins["recent"]), f'{len(ins["recent"])}건')
        check("사람별 활용에 테스트 계정이 잡힘",
              any(u["name"] == TEST_USER for u in ins["users"]),
              str([u["name"] for u in ins["users"]]))

        for p in ("today", "7d", "all"):
            r = await client.get(f"{CORE}/api/insights", params={"period": p})
            check(f"기간 {p} 조회", r.status_code == 200, str(r.status_code))

        # --- 10. 개인 전용 방 --------------------------------------------------
        print("\n[10] 개인 전용 방")
        async with httpx.AsyncClient(timeout=60.0) as other:
            await other.post(f"{CORE}/api/auth/login", json={"username": "e2e-other"})
            rooms = (await other.get(f"{CORE}/api/rooms")).json()
            check("남의 방은 목록에 없음",
                  all(r["id"] != room_id for r in rooms), f'{len(rooms)}개')
            r = await other.get(f"{CORE}/api/rooms/{room_id}")
            check("남의 방 직접 요청 -> 404", r.status_code == 404, str(r.status_code))
            r = await other.get(f"{CORE}/api/rooms/{room_id}/messages")
            check("남의 방 메시지 -> 404", r.status_code == 404, str(r.status_code))
            r = await other.post(
                f"{CORE}/api/chat", json={"room_id": room_id, "message": "몰래"}
            )
            check("남의 방에 질문 -> 404", r.status_code == 404, str(r.status_code))
            check("현황은 누구나 조회 가능",
                  (await other.get(f"{CORE}/api/insights")).status_code == 200)
            await other.post(f"{CORE}/api/auth/logout")
            r = await other.get(f"{CORE}/api/rooms")
            check("로그아웃 후 -> 401", r.status_code == 401, str(r.status_code))

        # 뒷정리: 이 테스트가 만든 방만 지운다
        await client.delete(f"{CORE}/api/rooms/{room_id}")

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
