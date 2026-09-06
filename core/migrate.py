"""아주 작은 마이그레이션 - 기존 테이블에 컬럼을 덧붙인다.

`create_all` 은 없는 테이블만 만들고 **기존 테이블은 손대지 않는다.** 그래서 나중에 추가한
컬럼은 이미 만들어진 DB 에 반영되지 않는다. Alembic 을 쓸 만큼 스키마가 복잡하지 않아
여기에 멱등한 문장을 늘어놓는 방식을 쓴다.

규칙:
  - `ADD COLUMN IF NOT EXISTS` 만 쓴다. 여러 번 돌려도 안전해야 한다.
  - 컬럼을 지우거나 타입을 바꾸지 않는다. 그런 변경이 필요하면 그때 제대로 된 도구를 쓴다.
  - 새 문장은 목록 끝에 덧붙인다. 순서가 곧 이력이다.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from core.db import engine

log = logging.getLogger("migrate")

# 실행 순서대로. 각 항목은 (설명, SQL).
STATEMENTS: list[tuple[str, str]] = [
    (
        "rooms.user_id - 방 주인",
        "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS user_id INTEGER "
        "REFERENCES users(id) ON DELETE CASCADE",
    ),
    (
        "messages.user_id - 질문한 사람",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_id INTEGER",
    ),
    (
        "agent_runs.user_id - 사용자별 집계용",
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_id INTEGER",
    ),
    (
        "agent_runs.num_ctx - 실측 num_ctx",
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS num_ctx INTEGER",
    ),
    (
        "rooms.user_id 인덱스",
        "CREATE INDEX IF NOT EXISTS ix_rooms_user_id ON rooms (user_id)",
    ),
    (
        "messages.user_id 인덱스",
        "CREATE INDEX IF NOT EXISTS ix_messages_user_id ON messages (user_id)",
    ),
    (
        "agent_runs.user_id 인덱스",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id)",
    ),
    # 처음엔 CASCADE 로 만들었는데, 그러면 사용자를 지울 때 그 사람의 대화가 통째로 사라진다.
    # 사람은 지우지 말고 is_active 를 끄는 것이 정석이지만, 실수로 지워도 대화는 남아야 한다.
    # 항상 지우고 다시 걸므로 여러 번 돌려도 안전하다.
    (
        "rooms.user_id 외래키를 SET NULL 로",
        "ALTER TABLE rooms DROP CONSTRAINT IF EXISTS rooms_user_id_fkey",
    ),
    (
        "rooms.unread - 스케줄이 남긴 안 읽은 결과 수",
        "ALTER TABLE rooms ADD COLUMN IF NOT EXISTS unread INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "rooms.user_id 외래키 재생성",
        "ALTER TABLE rooms ADD CONSTRAINT rooms_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL",
    ),
    (
        "room_agents.position - 순차 실행 순서",
        "ALTER TABLE room_agents ADD COLUMN IF NOT EXISTS position INTEGER "
        "NOT NULL DEFAULT 0",
    ),
]


async def run() -> None:
    """기동 시 create_all 직후에 호출한다."""
    async with engine.begin() as conn:
        for label, sql in STATEMENTS:
            try:
                await conn.execute(text(sql))
            except Exception:  # noqa: BLE001 - 한 문장이 실패해도 어디서 막혔는지는 남긴다
                log.exception("마이그레이션 실패: %s", label)
                raise
    log.info("마이그레이션 %d개 확인 완료", len(STATEMENTS))
