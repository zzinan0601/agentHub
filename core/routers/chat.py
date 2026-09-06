"""대화 API - 질문을 받아 에이전트를 부르고 NDJSON 으로 흘려보낸다.

SSE 가 아니라 streamable HTTP(application/x-ndjson)다.
브라우저는 fetch + ReadableStream 으로 한 줄씩 읽는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import current_user
from core.chat_service import build_state, busy_blockers, is_running, stream_chat
from core.db import get_session
from core.models import Message, Room, User

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    room_id: int
    message: str


def _busy_message(blocked: list[dict]) -> str:
    """기다릴지 말지 판단할 수 있게 누가 얼마나 쓰고 있는지까지 적는다."""
    parts = [f"{b['by']} 님이 '{b['name']}' 을(를) {b['seconds']}초째" for b in blocked]
    return " / ".join(parts) + " 쓰는 중입니다. 끝나면 다시 시도하세요."


@router.post("/chat")
async def chat(
    body: ChatIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    room = await session.get(Room, body.room_id)
    if room is None or room.user_id != user.id:
        raise HTTPException(status_code=404, detail="room not found")

    # 같은 방에 두 실행이 겹치면 대화 순서가 엉킨다. 하나만 돌린다.
    if is_running(room.id):
        raise HTTPException(status_code=409, detail="이 대화방에서 이미 실행 중입니다.")

    # 폐쇄망의 로컬 모델은 응답이 길다. 남이 쓰는 중인 에이전트를 또 부르면
    # Ollama 를 나눠 쓰며 둘 다 느려지므로, 비기를 기다리게 한다.
    blocked = busy_blockers(room)
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=_busy_message(blocked),
            headers={"X-Busy-Agents": ",".join(b["agent_id"] for b in blocked)},
        )

    # 이번 질문은 context 에 들어가면 안 되므로 상태를 먼저 만들고 나서 저장한다.
    state = await build_state(session, room, body.message, who=user.display_name)
    session.add(
        Message(room_id=room.id, user_id=user.id, role="user", content_md=body.message, meta={})
    )

    # 첫 질문이면 그 내용으로 방 제목을 지어준다.
    if room.title == "새 대화":
        room.title = body.message[:30]
    await session.commit()

    return StreamingResponse(
        stream_chat(state, room.id, user_id=user.id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
