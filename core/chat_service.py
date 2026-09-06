"""대화 실행 공통 로직 - 채팅 API 와 스케줄러가 함께 쓴다.

**실행과 전송을 분리한다.** 예전에는 그래프를 도는 것과 브라우저로 흘리는 것이 같은
제너레이터였는데, 그러면 브라우저가 끊길 때 Starlette 이 제너레이터를 닫아 마지막의
저장 코드에 도달하지 못했다. 폐쇄망에서 몇 분 걸린 응답을 탭 하나 닫았다고 통째로
잃는 셈이라, 실행을 별도 태스크로 떼어 **끊겨도 끝까지 돌고 저장하게** 했다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import SessionLocal
from core.graph import ChatState, run_chat
from core.harness import get_workflow
from core.models import AgentRun, Message, Room
from core.registry import registry

log = logging.getLogger("chat")

# 지금 돌고 있는 실행. 방 하나에 하나만 둔다.
# - 중단(cancel) 대상을 찾는 데 쓰고
# - 같은 방에 두 실행이 겹쳐 대화 순서가 엉키는 것을 막고
# - 태스크 참조를 붙들어 GC 가 가져가지 못하게 한다
_running: dict[int, asyncio.Task] = {}
_DONE = object()


def is_running(room_id: int) -> bool:
    return room_id in _running


def cancel(room_id: int) -> bool:
    """실행 중이면 중단한다. 중단해도 그때까지 받은 부분 결과는 저장된다."""
    task = _running.get(room_id)
    if task is None:
        return False
    task.cancel()
    return True


def busy_blockers(room: Room) -> list[dict[str, Any]]:
    """이 방이 부르려는 에이전트 중 지금 남이 쓰고 있는 것.

    채팅 API 와 스케줄러가 이 함수 하나를 함께 쓴다. 두 곳이 각자 검사하면 규칙이 갈라진다.
    자동 선택(고른 것도 워크플로우도 없음)은 라우터가 비어 있는 것만 후보로 삼으므로
    여기서는 '부를 수 있는 게 하나도 없는' 경우만 막는다.
    """
    wanted: list[str] = []
    if room.workflow:
        wf = get_workflow(room.workflow) or {}
        wanted = [s.get("agent") for s in (wf.get("steps") or []) if isinstance(s, dict)]
    elif room.agents:
        wanted = [a.agent_id for a in room.agents]

    if not wanted:
        # 자동 선택. 부를 수 있는 에이전트가 하나라도 있으면 통과시킨다.
        if registry.callable() or not registry.online():
            return []
        return [
            {"agent_id": a.id, "name": a.to_dict()["name"], "by": a.busy_by,
             "seconds": a.to_dict()["busy_seconds"]}
            for a in registry.online()
        ]

    blocked = []
    for agent_id in wanted:
        agent = registry.get(agent_id)
        if agent and agent.busy_by is not None:
            blocked.append(
                {"agent_id": agent.id, "name": agent.to_dict()["name"],
                 "by": agent.busy_by, "seconds": agent.to_dict()["busy_seconds"]}
            )
    return blocked


async def recent_context(session: AsyncSession, room_id: int) -> list[dict[str, str]]:
    """에이전트에게 넘길 최근 대화. 최신 N턴을 가져와 오래된 순으로 돌려준다."""
    rows = list(
        await session.scalars(
            select(Message)
            .where(Message.room_id == room_id, Message.role.in_(("user", "assistant")))
            .order_by(Message.id.desc())
            .limit(settings.context_turns)
        )
    )
    return [{"role": m.role, "content": m.content_md} for m in reversed(rows)]


async def build_state(
    session: AsyncSession, room: Room, query: str, who: str = ""
) -> ChatState:
    """방 설정을 그래프 상태로 옮긴다."""
    return ChatState(
        room_id=room.id,
        query=query,
        model=room.model,
        context=await recent_context(session, room.id),
        selected=[a.agent_id for a in room.agents],
        mode=room.mode,
        workflow=room.workflow,
        who=who,
    )


async def _save(
    room_id: int,
    role: str,
    markdown: str,
    meta: dict[str, Any],
    runs: list[dict[str, Any]],
    user_id: int | None,
) -> None:
    """최종 답변과 에이전트 호출 기록을 저장한다. 응답 스트림과는 별도 세션을 쓴다."""
    async with SessionLocal() as session:
        session.add(
            Message(
                room_id=room_id, user_id=user_id, role=role, content_md=markdown, meta=meta
            )
        )
        for run in runs:
            session.add(
                AgentRun(
                    room_id=room_id,
                    user_id=user_id,
                    agent_id=run.get("agent_id") or "?",
                    status=run.get("status", "ok"),
                    elapsed_ms=run.get("elapsed_ms", 0),
                    num_ctx=run.get("num_ctx"),
                    error=run.get("error"),
                )
            )
        await session.commit()


async def _run_and_save(
    state: ChatState,
    room_id: int,
    role: str,
    user_id: int | None,
    queue: asyncio.Queue | None,
) -> str:
    """그래프를 끝까지 돌리고 결과를 저장한다. 최종 Markdown 을 돌려준다.

    queue 가 있으면 이벤트를 그리로도 흘려보낸다(브라우저 중계용). 이 함수는 응답
    스트림과 **별개의 태스크**로 돌기 때문에, 브라우저가 끊겨도 여기까지는 끝난다.
    """
    runs: list[dict[str, Any]] = []
    final_markdown, final_meta = "", {}
    cancelled = False

    try:
        async for event in run_chat(state):
            etype = event.get("type")
            agent_id = event.get("agent_id")

            # 에이전트별 성공/실패를 모아두었다가 마지막에 한 번에 저장한다.
            if agent_id and etype in ("result", "error"):
                emeta = event.get("meta") or {}
                runs.append(
                    {
                        "agent_id": agent_id,
                        "status": "ok" if etype == "result" else "error",
                        "elapsed_ms": emeta.get("elapsed_ms", 0),
                        # 에이전트가 실제로 쓴 num_ctx. 추정치 보정에 쓰려고 남긴다.
                        "num_ctx": emeta.get("num_ctx"),
                        # 실제로 쓴 모델. .env 로 고정해 두면 방에서 고른 것과 다를 수
                        # 있으므로, 화면이 방의 모델만 보고 거짓말하지 않게 함께 남긴다.
                        "model": emeta.get("model"),
                        "error": event.get("message"),
                    }
                )

            # agent_id 가 없는 종료 이벤트 = 코어가 만든 최종 결과
            if not agent_id and etype == "result":
                final_markdown = event.get("markdown", "")
                final_meta = {
                    "attachments": event.get("attachments", []),
                    # 실행 트레이스. 지난 대화를 다시 열어도 "이 답이 어떻게 나왔는지" 보인다.
                    "runs": runs,
                    **(event.get("meta") or {}),
                }
            elif not agent_id and etype == "error":
                final_markdown = f"## 오류\n\n{event.get('message', '')}"

            if queue is not None:
                queue.put_nowait(json.dumps(event, ensure_ascii=False) + "\n")
    except asyncio.CancelledError:
        # 사용자가 중단했다. 여기까지 받은 것은 버리지 않는다.
        # 몇 분치 작업이 통째로 사라지면 중단 버튼을 누르기가 무섭다.
        cancelled = True
        final_meta.setdefault("runs", runs)
        final_meta["cancelled"] = True
        if not final_markdown:
            final_markdown = "_중단되었습니다._"
    except Exception as exc:  # noqa: BLE001 - 그래프가 터져도 답은 남겨야 한다
        log.exception("실행 실패 room=%s", room_id)
        final_markdown = final_markdown or f"## 오류\n\n{type(exc).__name__}: {exc}"
        final_meta.setdefault("runs", runs)
    if cancelled:
        # 취소된 태스크 안에서 await 하면 곧바로 다시 취소된다.
        # 저장만 떼어내 별도 태스크로 끝까지 돌린다.
        _detached_save(room_id, role, final_markdown, final_meta, runs, user_id)
        if queue is not None:
            queue.put_nowait(_DONE)
        raise asyncio.CancelledError

    try:
        await _save(room_id, role, final_markdown, final_meta, runs, user_id)
    finally:
        # 저장까지 끝난 **뒤에** 스트림을 닫는다. 먼저 닫으면 브라우저는 답을 다 받았는데
        # 서버는 아직 이 방을 '실행 중'으로 들고 있어, 곧바로 다음 질문을 보내면
        # 409 로 튕긴다. 어떤 경로로 끝나든 닫아야 스트림이 영영 안 닫히는 일이 없다.
        if queue is not None:
            queue.put_nowait(_DONE)
    return final_markdown


# 떼어낸 저장 태스크. 참조를 붙들지 않으면 GC 가 중간에 가져갈 수 있다.
_savers: set[asyncio.Task] = set()


def _detached_save(*args: Any) -> None:
    task = asyncio.create_task(_save(*args))
    _savers.add(task)
    task.add_done_callback(_savers.discard)


def _forget(room_id: int) -> None:
    _running.pop(room_id, None)


async def stream_chat(
    state: ChatState, room_id: int, role: str = "assistant", user_id: int | None = None
) -> AsyncIterator[str]:
    """실행을 별도 태스크로 띄우고, 그 태스크가 뱉는 줄을 브라우저로 흘려보낸다.

    큐는 무제한이다. 브라우저가 끊겨 아무도 읽지 않을 때 put 에서 막히면 결국
    실행도 멈추므로, 크기를 두지 않고 put_nowait 만 쓴다.
    """
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run_and_save(state, room_id, role, user_id, queue))
    _running[room_id] = task
    task.add_done_callback(lambda _: _forget(room_id))

    while (item := await queue.get()) is not _DONE:
        yield item


async def run_once(
    state: ChatState, room_id: int, role: str = "schedule", user_id: int | None = None
) -> str:
    """스트리밍 없이 끝까지 돌리고 최종 Markdown 을 돌려준다. (스케줄 실행용)

    스케줄도 중단 대상이 되어야 하므로 채팅과 똑같이 _running 에 올린다.
    """
    task = asyncio.create_task(_run_and_save(state, room_id, role, user_id, None))
    _running[room_id] = task
    task.add_done_callback(lambda _: _forget(room_id))
    return await task
