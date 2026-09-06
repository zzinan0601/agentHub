"""스케줄 API - 방마다 하나만. (요구사항 16)"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core import scheduler as sched
from core.config import settings
from core.db import get_session
from core.models import Room, Schedule

router = APIRouter(prefix="/api/rooms", tags=["schedules"])
# cron 미리보기는 특정 방에 속하지 않으므로 경로를 따로 둔다.
cron_router = APIRouter(prefix="/api", tags=["schedules"])


@cron_router.get("/cron/preview")
async def preview_cron(expr: str, count: int = 3) -> dict:
    """cron 식이 실제로 언제 도는지 미리 보여준다.

    "3시간마다" 같은 주기를 글로 설명하는 것보다 다음 실행 시각 몇 개를 보여주는 편이
    오해가 없다. 화면에서 입력하는 동안 호출된다.
    """
    try:
        trigger = sched.validate_cron(expr)
    except ValueError as exc:
        return {"valid": False, "error": str(exc), "next": []}

    times, previous = [], None
    for _ in range(max(1, min(count, 5))):
        # 앞서 구한 시각 바로 뒤부터 다시 찾아 연속된 실행 시각을 얻는다.
        nxt = trigger.get_next_fire_time(previous, previous or datetime.now(ZoneInfo(settings.timezone)))
        if nxt is None:
            break
        times.append(nxt.strftime("%m-%d %H:%M"))
        previous = nxt
    return {"valid": True, "error": None, "next": times}


class ScheduleIn(BaseModel):
    cron: str  # "분 시 일 월 요일"  예) 0 9 * * 1-5  = 평일 오전 9시
    prompt: str  # 그 시각에 대신 던질 질문
    enabled: bool = True


def _to_dict(schedule: Schedule) -> dict:
    return {
        "room_id": schedule.room_id,
        "cron": schedule.cron,
        "prompt": schedule.prompt,
        "enabled": schedule.enabled,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "next_run_at": sched.next_run_at(schedule.room_id),
    }


@router.get("/{room_id}/schedule")
async def get_schedule(room_id: int, session: AsyncSession = Depends(get_session)) -> dict | None:
    schedule = await session.get(Schedule, room_id)
    return _to_dict(schedule) if schedule else None


@router.put("/{room_id}/schedule")
async def put_schedule(
    room_id: int, body: ScheduleIn, session: AsyncSession = Depends(get_session)
) -> dict:
    """스케줄을 만들거나 덮어쓴다. 방당 1개이므로 추가가 아니라 항상 교체다."""
    if await session.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail="room not found")
    try:
        sched.validate_cron(body.cron)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"cron 식이 잘못되었습니다: {exc}")

    schedule = await session.get(Schedule, room_id)
    if schedule is None:
        schedule = Schedule(room_id=room_id)
        session.add(schedule)
    schedule.cron = body.cron
    schedule.prompt = body.prompt
    schedule.enabled = body.enabled
    await session.commit()
    await session.refresh(schedule)

    sched.apply(room_id, body.cron, body.enabled)
    return _to_dict(schedule)


@router.delete("/{room_id}/schedule")
async def delete_schedule(room_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    schedule = await session.get(Schedule, room_id)
    if schedule:
        await session.delete(schedule)
        await session.commit()
    sched.remove(room_id)
    return {"deleted": room_id}
