"""채팅방 스케줄 - 방마다 하나씩만 걸 수 있다. (요구사항 16)

'방당 1개'는 schedules 테이블의 기본키가 room_id 라는 사실로 보장된다.
여기서는 APScheduler 의 job id 를 room:<id> 로 고정해 같은 규칙을 지킨다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MAX_INSTANCES
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from core.chat_service import build_state, busy_blockers, run_once
from core.config import settings
from core.db import SessionLocal
from core.models import Message, Room, Schedule

log = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _job_id(room_id: int) -> str:
    return f"room:{room_id}"


def validate_cron(expr: str) -> CronTrigger:
    """cron 식이 올바른지 확인한다. 잘못되면 ValueError 가 난다."""
    return CronTrigger.from_crontab(expr, timezone=settings.timezone)


async def _note_skip(room_id: int, why: str, detail: str) -> None:
    """이번 차례를 건너뛴 사실을 방에 남긴다.

    로그에만 찍으면 아무도 모른다. 사용자는 "왜 결과가 없지?" 만 남는다.
    messages.role 은 제약 없는 문자열이라 새 값을 넣어도 마이그레이션이 필요 없다.
    """
    log.warning("스케줄 건너뜀 room=%s (%s)", room_id, why)
    async with SessionLocal() as session:
        room = await session.get(Room, room_id)
        if room is None:
            return
        session.add(
            Message(
                room_id=room_id,
                user_id=room.user_id,
                role="system",
                content_md=detail,
                meta={"skipped": why},
            )
        )
        room.unread = (room.unread or 0) + 1
        await session.commit()


def _on_max_instances(event) -> None:
    """앞 실행이 아직 안 끝나 이번 차례를 건너뛴 경우 (APScheduler 가 알려준다)."""
    room_id = int(event.job_id.split(":")[1])
    asyncio.create_task(
        _note_skip(
            room_id,
            "overlap",
            "앞 실행이 끝나지 않아 이번 예약을 건너뛰었습니다. 주기를 늘려보세요.",
        )
    )


async def _fire(room_id: int) -> None:
    """예약 시각이 되면 저장해 둔 질문을 대신 던지고 결과를 방에 남긴다."""
    async with SessionLocal() as session:
        room = await session.get(Room, room_id)
        schedule = await session.get(Schedule, room_id)
        if room is None or schedule is None or not schedule.enabled:
            return

        # 사람이 먼저 쓰고 있으면 비켜준다. 겹쳐 부르면 둘 다 느려진다.
        blocked = busy_blockers(room)
        if blocked:
            names = ", ".join(f"{b['by']} 님이 쓰는 '{b['name']}'" for b in blocked)
            await _note_skip(room_id, "agent_busy", f"{names} 때문에 이번 예약을 건너뛰었습니다.")
            return

        state = await build_state(session, room, schedule.prompt, who="스케줄")
        prompt = schedule.prompt
        owner_id = room.user_id  # 사람이 없으므로 방 주인 앞으로 기록한다
        # 예약된 질문도 대화에 남긴다. 남기지 않으면 화면에 결과만 덩그러니 보인다.
        session.add(
            Message(
                room_id=room_id,
                user_id=owner_id,
                role="user",
                content_md=prompt,
                meta={"scheduled": True},
            )
        )
        await session.commit()

    log.info("스케줄 실행 room=%s: %.40s", room_id, prompt)
    try:
        await run_once(state, room_id, role="schedule", user_id=owner_id)
    except asyncio.CancelledError:
        log.info("스케줄 실행이 중단됐습니다 room=%s", room_id)
    except Exception:  # noqa: BLE001 - 한 번 실패해도 다음 예약은 살아 있어야 한다
        log.exception("스케줄 실행 실패 room=%s", room_id)

    async with SessionLocal() as session:
        schedule = await session.get(Schedule, room_id)
        if schedule:
            schedule.last_run_at = datetime.now(ZoneInfo(settings.timezone))
        # 사람이 없을 때 돈 결과다. 방 목록에서 눈에 띄게 해두지 않으면 그대로 묻힌다.
        room = await session.get(Room, room_id)
        if room:
            room.unread = (room.unread or 0) + 1
        await session.commit()


def apply(room_id: int, cron: str, enabled: bool) -> None:
    """스케줄을 등록/교체한다. 같은 방의 기존 예약은 자동으로 대체된다."""
    remove(room_id)
    if not enabled:
        return
    scheduler.add_job(
        _fire,
        trigger=validate_cron(cron),
        id=_job_id(room_id),
        args=[room_id],
        replace_existing=True,
        # 같은 방의 실행이 겹치지 않게 한다. 겹치면 아래 리스너가 방에 기록을 남긴다.
        max_instances=1,
        misfire_grace_time=300,  # 코어가 잠깐 꺼져 있었어도 5분 안이면 실행한다
    )


def remove(room_id: int) -> None:
    job = scheduler.get_job(_job_id(room_id))
    if job:
        job.remove()


def next_run_at(room_id: int) -> str | None:
    job = scheduler.get_job(_job_id(room_id))
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def install_listeners() -> None:
    """겹쳐서 건너뛴 것을 방에 남기려면 이 이벤트를 잡아야 한다."""
    scheduler.add_listener(_on_max_instances, EVENT_JOB_MAX_INSTANCES)


async def load_all() -> None:
    """코어 기동 시 DB 에 저장된 스케줄을 다시 등록한다."""
    async with SessionLocal() as session:
        rows = await session.scalars(select(Schedule).where(Schedule.enabled.is_(True)))
        for schedule in rows:
            try:
                apply(schedule.room_id, schedule.cron, True)
            except ValueError:
                log.warning("잘못된 cron 이라 건너뜁니다 room=%s: %s", schedule.room_id, schedule.cron)
    log.info("스케줄 %d개 등록", len(scheduler.get_jobs()))
