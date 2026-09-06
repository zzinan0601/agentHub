"""활용 현황 - 어떤 질문이 많고 어떤 에이전트가 자주 불리는지.

집계는 전부 SQL 로 한다. 파이썬으로 끌어와 세지 않는다.
로그인만 하면 누구나 본다 (전원 공개 결정). 각 개발자가 자기 에이전트가 잘 쓰이는지
알아야 하기 때문이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import current_user
from core.config import settings
from core.db import get_session
from core.models import User
from core.registry import registry
from core.similar import group_questions

router = APIRouter(prefix="/api/insights", tags=["insights"])

# 기간 선택지. 값은 '며칠 전부터' 이고 None 이면 전체.
PERIODS = {"today": 0, "7d": 7, "30d": 30, "all": None}

# "전체" 를 NULL 로 표현하면 PostgreSQL 이 파라미터 타입을 못 정한다
# (could not determine data type of parameter). 아주 오래된 시각을 넘기면
# 조건이 `created_at >= :since` 하나로 끝나 SQL 도 단순해진다.
BEGINNING = datetime(1970, 1, 1, tzinfo=timezone.utc)

# 일자별 그래프에 그릴 최대 일수. 이보다 오래됐으면 최근 것만 그린다.
# 막대가 100개를 넘어가면 날짜를 읽을 수 없어 그래프의 뜻이 없어진다.
DAILY_MAX_DAYS = 90


def _since(period: str) -> datetime:
    """기간 문자열을 기준 시각으로 바꾼다."""
    days = PERIODS.get(period, 7)
    if days is None:
        return BEGINNING
    now = datetime.now(timezone.utc)
    if days == 0:  # 오늘은 자정부터
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=days)


def _ms(value) -> int:
    return int(value or 0)


def _used_model(meta: dict) -> str | None:
    """그 답을 만들 때 **실제로 쓰인** 모델.

    방에서 고른 모델(meta.model)과 다를 수 있다. 에이전트가 자기 .env 의 AGENT_MODEL 로
    고정해 두면 화면 선택을 따르지 않기 때문이다. 방의 선택을 그대로 보여주면 화면이
    거짓말을 하게 되므로, 에이전트가 남긴 실측값을 우선한다.
    에이전트를 하나도 안 불렀다면(직접 답변) 코어가 쓴 모델이 곧 답이다.
    """
    used = sorted({r.get("model") for r in (meta or {}).get("runs") or [] if r.get("model")})
    if used:
        return ", ".join(used)
    return (meta or {}).get("model")


def _core_ms(meta: dict) -> int:
    """코디네이터 LLM 이 쓴 시간. 라우팅 + 합치기 + 직접 답변."""
    t = (meta or {}).get("timings") or {}
    return sum(_ms(t.get(k)) for k in ("route_ms", "reduce_ms", "direct_ms"))


@router.get("")
async def insights(
    period: str = Query("7d", pattern="^(today|7d|30d|all)$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
) -> dict:
    """현황 화면이 쓰는 단일 엔드포인트. 한 번에 다 내려준다."""
    since = _since(period)
    # 기간 조건을 문자열로 조립하지 않고 바인드 파라미터로 넘긴다.
    where_runs = "where created_at >= :since"
    where_msgs = "where created_at >= :since"
    params = {"since": since}

    # --- 요약 ---------------------------------------------------------------
    summary = (
        await db.execute(
            text(f"""
            select
              (select count(*) from messages {where_msgs} and role = 'user') as questions,
              (select count(*) from agent_runs {where_runs}) as calls,
              (select count(*) from agent_runs {where_runs} and status = 'error') as errors,
              (select round(avg(elapsed_ms)) from agent_runs {where_runs} and status = 'ok')
                as avg_ms,
              (select count(distinct user_id) from messages {where_msgs} and role = 'user')
                as users,
              -- 앞 실행과 겹치거나 에이전트가 잡혀 있어 건너뛴 예약. 쌓이면 주기가 짧다는 뜻이다.
              (select count(*) from messages {where_msgs} and role = 'system'
                 and meta->>'skipped' is not null) as skipped
        """),
            params,
        )
    ).mappings().one()

    calls = summary["calls"] or 0
    # --- 일자별 질문 수 -------------------------------------------------------
    #
    # 질문이 없던 날도 0 으로 채운다. 있는 날만 이어 붙이면 8/28 옆에 9/1 이 붙어
    # 사흘이 비었다는 사실이 사라진다. 날짜를 보여주는 그래프에서는 그게 거짓말이 된다.
    # 막대가 너무 많으면 읽을 수 없으므로 최근 DAILY_MAX_DAYS 일로 자른다.
    daily = (
        await db.execute(
            text(f"""
            with span as (
              select cast(max(created_at) as date) as last_day,
                     greatest(
                       cast(:since as date),
                       cast(min(created_at) as date),
                       cast(max(created_at) as date) - cast(:max_days as int) + 1
                     ) as first_day
              from messages {where_msgs} and role = 'user'
            )
            select to_char(d, 'MM-DD') as day,
                   (select count(*) from messages m
                     where m.role = 'user'
                       and m.created_at >= d and m.created_at < d + interval '1 day') as n
            from span,
                 generate_series(span.first_day, span.last_day, interval '1 day') as d
            order by d
        """),
            {**params, "max_days": DAILY_MAX_DAYS},
        )
    ).mappings().all()

    # --- ① 에이전트별 활용 -----------------------------------------------------
    # p95 는 percentile_cont 로 구한다. 평균만 보면 가끔 튀는 호출이 묻힌다.
    agent_rows = (
        await db.execute(
            text(f"""
            select agent_id,
                   count(*) as calls,
                   count(*) filter (where status = 'error') as errors,
                   round(avg(elapsed_ms) filter (where status = 'ok')) as avg_ms,
                   round(percentile_cont(0.95) within group (order by elapsed_ms)
                         filter (where status = 'ok')) as p95_ms,
                   max(elapsed_ms) as max_ms,
                   round(avg(num_ctx)) as avg_num_ctx,
                   max(num_ctx) as max_num_ctx,
                   max(created_at) as last_at
            from agent_runs {where_runs}
            group by agent_id
        """),
            params,
        )
    ).mappings().all()
    stats = {r["agent_id"]: r for r in agent_rows}

    # registry 의 manifest(이름·담당자·온라인)를 붙인다. 등록됐지만 한 번도 안 불린
    # 에이전트도 목록에 남겨야 "안 쓰이고 있다" 는 사실이 보인다.
    agents: list[dict] = []
    for info in registry.all():
        row = stats.get(info.id)
        n = row["calls"] if row else 0
        errors = row["errors"] if row else 0
        agents.append(
            {
                "agent_id": info.id,
                "name": info.manifest.name if info.manifest else info.id,
                "owner": info.manifest.owner if info.manifest else "",
                "online": info.online,
                "contract_mismatch": info.contract_mismatch,
                "calls": n,
                "errors": errors,
                "fail_rate": round(errors / n, 3) if n else 0.0,
                "avg_ms": _ms(row["avg_ms"]) if row else 0,
                "p95_ms": _ms(row["p95_ms"]) if row else 0,
                "max_ms": _ms(row["max_ms"]) if row else 0,
                "avg_num_ctx": _ms(row["avg_num_ctx"]) if row else 0,
                "max_num_ctx": _ms(row["max_num_ctx"]) if row else 0,
                "last_at": row["last_at"].isoformat() if row and row["last_at"] else None,
            }
        )
    # registry 에 없는데 기록만 남은 에이전트(등록 해제됨)도 보여준다.
    known = {a["agent_id"] for a in agents}
    for agent_id, row in stats.items():
        if agent_id in known:
            continue
        agents.append(
            {
                "agent_id": agent_id,
                "name": agent_id,
                "owner": "",
                "online": False,
                "contract_mismatch": False,
                "unregistered": True,  # registry.yaml 에서 빠진 것
                "calls": row["calls"],
                "errors": row["errors"],
                "fail_rate": round(row["errors"] / row["calls"], 3) if row["calls"] else 0.0,
                "avg_ms": _ms(row["avg_ms"]),
                "p95_ms": _ms(row["p95_ms"]),
                "max_ms": _ms(row["max_ms"]),
                "avg_num_ctx": _ms(row["avg_num_ctx"]),
                "max_num_ctx": _ms(row["max_num_ctx"]),
                "last_at": row["last_at"].isoformat() if row["last_at"] else None,
            }
        )
    agents.sort(key=lambda a: a["calls"], reverse=True)

    # --- ② 최근 질문 ----------------------------------------------------------
    # 질문과 답변을 잇기 위해 스키마를 바꾸지 않고, 같은 방에서 바로 다음 메시지를 붙인다.
    questions = (
        await db.execute(
            text(f"""
            with ordered as (
                select id, room_id, user_id, role, content_md, meta, created_at,
                       lead(meta) over (partition by room_id order by id) as answer_meta,
                       lead(role) over (partition by room_id order by id) as answer_role
                from messages
            )
            select o.id, o.room_id, o.content_md, o.created_at, o.meta, o.answer_meta,
                   u.display_name, r.title as room_title
            from ordered o
            left join users u on u.id = o.user_id
            left join rooms r on r.id = o.room_id
            where o.role = 'user'
              and o.created_at >= :since
              and o.answer_role in ('assistant', 'schedule')
            order by o.id desc
            limit :limit
        """),
            {**params, "limit": limit},
        )
    ).mappings().all()

    recent = []
    for q in questions:
        ameta = q["answer_meta"] or {}
        runs = ameta.get("runs") or []
        plan = ameta.get("plan") or {}
        recent.append(
            {
                "question": q["content_md"],
                "user": q["display_name"] or "(알 수 없음)",
                "room_id": q["room_id"],
                "room_title": q["room_title"],
                "created_at": q["created_at"].isoformat(),
                "scheduled": bool((q["meta"] or {}).get("scheduled")),
                "agents": [r.get("agent_id") for r in runs],
                "failed": [r.get("agent_id") for r in runs if r.get("status") == "error"],
                "elapsed_ms": sum(_ms(r.get("elapsed_ms")) for r in runs),
                # 코디네이터가 쓴 시간. 에이전트 시간과 나눠야 어디를 고칠지 보인다.
                "core_ms": _core_ms(ameta),
                "mode": plan.get("mode"),
                "source": plan.get("source"),
                "model": _used_model(ameta),
            }
        )

    # --- ②-1. 자주 묻는 질문 ---------------------------------------------------
    # 표현이 조금씩 달라도 같은 질문이면 함께 센다. 그러지 않으면 잘게 쪼개져
    # 무엇이 자주 묻는 질문인지 드러나지 않는다.
    asked = (
        await db.execute(
            text("""
            with ordered as (
                select id, room_id, role, content_md, created_at,
                       lead(meta) over (partition by room_id order by id) as answer_meta,
                       lead(role) over (partition by room_id order by id) as answer_role
                from messages
            )
            select content_md, created_at, answer_meta
            from ordered
            where role = 'user' and created_at >= :since
              and answer_role in ('assistant', 'schedule')
            order by id desc
            limit :sample
        """),
            {**params, "sample": settings.insight_sample},
        )
    ).mappings().all()

    frequent = group_questions(
        [
            {
                "text": a["content_md"],
                "created_at": a["created_at"],
                "model": _used_model(a["answer_meta"] or {}),
                "agents": [
                    r.get("agent_id") for r in ((a["answer_meta"] or {}).get("runs") or [])
                ],
                "elapsed_ms": sum(
                    _ms(r.get("elapsed_ms"))
                    for r in ((a["answer_meta"] or {}).get("runs") or [])
                ),
            }
            for a in asked
        ],
        threshold=settings.insight_similarity,
        limit=8,
    )

    # --- ④ 라우팅 분석 --------------------------------------------------------
    routing = (
        await db.execute(
            text(f"""
            select
              coalesce(meta->'plan'->>'source', 'auto') as source,
              coalesce(meta->'plan'->>'mode', 'parallel') as mode,
              jsonb_array_length(coalesce(meta->'plan'->'agents', '[]'::jsonb)) as agent_count,
              count(*) as n
            from messages {where_msgs}
              and role in ('assistant', 'schedule')
              and meta ? 'plan'
            group by 1, 2, 3
        """),
            params,
        )
    ).mappings().all()

    by_source: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    no_agent = 0
    routed_total = 0
    for r in routing:
        n = r["n"]
        routed_total += n
        by_source[r["source"]] = by_source.get(r["source"], 0) + n
        if r["agent_count"] == 0:
            no_agent += n
        elif r["agent_count"] == 1:
            by_mode["single"] = by_mode.get("single", 0) + n
        else:
            by_mode[r["mode"]] = by_mode.get(r["mode"], 0) + n

    # 에이전트를 아무도 부르지 않은 질문의 예시. 커버리지 공백을 찾는 실마리가 된다.
    uncovered = (
        await db.execute(
            text("""
            with ordered as (
                select room_id, role, content_md, created_at,
                       lead(meta) over (partition by room_id order by id) as answer_meta,
                       lead(role) over (partition by room_id order by id) as answer_role
                from messages
            )
            select content_md from ordered
            where role = 'user' and answer_role in ('assistant', 'schedule')
              and created_at >= :since
              and jsonb_array_length(
                    coalesce(answer_meta->'plan'->'agents', '[]'::jsonb)) = 0
            order by created_at desc limit 5
        """),
            params,
        )
    ).scalars().all()

    # --- ⑤ 사용자별 활용 -------------------------------------------------------
    users = (
        await db.execute(
            text(f"""
            select u.display_name,
                   count(*) filter (where m.role = 'user') as questions,
                   (select count(*) from agent_runs ar
                      where ar.user_id = u.id and ar.created_at >= :since) as calls,
                   max(m.created_at) as last_at
            from messages m join users u on u.id = m.user_id
            where m.created_at >= :since and m.role = 'user'
            group by u.id, u.display_name
            order by questions desc
        """),
            params,
        )
    ).mappings().all()

    return {
        "period": period,
        "summary": {
            "questions": summary["questions"] or 0,
            "calls": calls,
            "errors": summary["errors"] or 0,
            "fail_rate": round((summary["errors"] or 0) / calls, 3) if calls else 0.0,
            "avg_ms": _ms(summary["avg_ms"]),
            "users": summary["users"] or 0,
            "skipped": summary["skipped"] or 0,
        },
        "daily": [{"day": d["day"], "count": d["n"]} for d in daily],
        "agents": agents,
        "frequent": frequent,
        "recent": recent,
        "routing": {
            "total": routed_total,
            "by_source": by_source,
            "by_mode": by_mode,
            "no_agent": no_agent,
            "no_agent_examples": list(uncovered),
        },
        "users": [
            {
                "name": u["display_name"],
                "questions": u["questions"],
                "calls": u["calls"],
                "last_at": u["last_at"].isoformat() if u["last_at"] else None,
            }
            for u in users
        ],
        "fail_rate_warn": settings.insight_fail_rate_warn,
        "similarity": settings.insight_similarity,
    }
