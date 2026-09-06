"""채팅방 API - 방은 여러 개 만들 수 있다. (요구사항 13)"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import chat_service
from core.auth import current_user
from core.config import settings
from core.db import get_session
from core.models import Message, Room, RoomAgent, User

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class RoomIn(BaseModel):
    """방 생성/수정 입력. 보내지 않은 항목은 기존 값을 유지한다."""

    title: str | None = None
    model: str | None = None
    mode: str | None = None  # parallel | sequential
    workflow: str | None = None
    agents: list[str] | None = None  # 사용자가 고른 에이전트 (빈 배열이면 LLM 자동 선택)


def _to_dict(room: Room) -> dict:
    return {
        "id": room.id,
        "title": room.title,
        "model": room.model,
        "mode": room.mode,
        "workflow": room.workflow,
        "agents": [a.agent_id for a in room.agents],
        "unread": room.unread or 0,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


async def _get_room(session: AsyncSession, room_id: int, user: User) -> Room:
    """내 방만 꺼낸다. 남의 방 id 로 접근하면 '없다' 고 답한다.

    403 이 아니라 404 로 답하는 이유는 남의 방이 존재한다는 사실조차 알릴 필요가 없기 때문이다.
    """
    room = await session.get(Room, room_id)
    if room is None or room.user_id != user.id:
        raise HTTPException(status_code=404, detail="room not found")
    return room


@router.get("")
async def list_rooms(
    session: AsyncSession = Depends(get_session), user: User = Depends(current_user)
) -> list[dict]:
    rows = await session.scalars(
        select(Room).where(Room.user_id == user.id).order_by(Room.id.desc())
    )
    return [_to_dict(r) for r in rows]


@router.post("")
async def create_room(
    body: RoomIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    room = Room(
        user_id=user.id,
        title=body.title or "새 대화",
        model=body.model or settings.default_model,  # 기본 모델은 .env 에서 (요구사항 18)
        mode=body.mode or "parallel",
        workflow=body.workflow,
    )
    session.add(room)
    await session.commit()
    await session.refresh(room)
    return _to_dict(room)


@router.get("/{room_id}")
async def get_room(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _to_dict(await _get_room(session, room_id, user))


@router.patch("/{room_id}")
async def update_room(
    room_id: int,
    body: RoomIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    room = await _get_room(session, room_id, user)
    if body.title is not None:
        room.title = body.title
    if body.model is not None:
        room.model = body.model
    if body.mode is not None:
        room.mode = body.mode
    # workflow 는 빈 문자열로 해제할 수 있어야 하므로 None 검사만 한다.
    if body.workflow is not None:
        room.workflow = body.workflow or None

    if body.agents is not None:
        await session.execute(delete(RoomAgent).where(RoomAgent.room_id == room_id))
        # 화면이 보낸 배열 순서가 곧 순차 실행 순서다. 인덱스를 그대로 저장한다.
        for i, agent_id in enumerate(body.agents):
            session.add(RoomAgent(room_id=room_id, agent_id=agent_id, position=i))

    await session.commit()
    await session.refresh(room)
    return _to_dict(room)


@router.delete("/{room_id}")
async def delete_room(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    room = await _get_room(session, room_id, user)
    await session.delete(room)  # 메시지/스케줄은 FK cascade 로 함께 지워진다
    await session.commit()
    return {"deleted": room_id}


@router.post("/{room_id}/read")
async def mark_read(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """방을 열어봤다고 표시한다. 스케줄 결과의 강조를 지운다.

    메시지를 읽어가는 GET 에서 슬쩍 처리하지 않고 따로 둔다.
    조회가 값을 바꾸면 나중에 원인을 찾기 어려워진다.
    """
    room = await _get_room(session, room_id, user)
    if room.unread:
        room.unread = 0
        await session.commit()
    return {"room_id": room_id, "unread": 0}


@router.get("/{room_id}/messages")
async def list_messages(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict]:
    await _get_room(session, room_id, user)  # 내 방인지 먼저 확인한다
    rows = await session.scalars(
        select(Message).where(Message.room_id == room_id).order_by(Message.id)
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content_md": m.content_md,
            "meta": m.meta or {},
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.delete("/{room_id}/run")
async def cancel_run(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """실행 중인 질문을 중단한다.

    폐쇄망의 로컬 모델은 한 번에 몇 분이 걸린다. 오타로 보낸 질문 하나에 그만큼을
    묶이지 않도록 빠져나갈 길을 둔다. 중단해도 그때까지 받은 부분 결과는 저장된다.
    """
    await _get_room(session, room_id, user)  # 내 방인지 먼저 확인한다
    return {"room_id": room_id, "cancelled": chat_service.cancel(room_id)}
