"""사용자 관리 CLI.

비밀번호가 없는 구조라 평소에는 쓸 일이 없다. 오타로 만들어진 이름을 정리하거나
팀을 떠난 사람을 막을 때 쓴다.

    python scripts/users.py list
    python scripts/users.py rename 홍길동 김영희      # 이름 바꾸기 (대화는 그대로 따라간다)
    python scripts/users.py disable 김철수            # 로그인 차단 (대화는 남는다)
    python scripts/users.py enable 김철수
    python scripts/users.py admin 김영희              # 관리자로 지정

사람을 '지우는' 명령은 일부러 넣지 않았다. 지우는 대신 disable 을 쓴다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from core.auth import normalize  # noqa: E402
from core.db import SessionLocal  # noqa: E402
from core.models import Message, Room, User  # noqa: E402


async def cmd_list() -> int:
    async with SessionLocal() as db:
        users = list(await db.scalars(select(User).order_by(User.created_at)))
        if not users:
            print("등록된 사용자가 없습니다. 화면에서 이름을 넣으면 그때 만들어집니다.")
            return 0
        print(f"{'이름':<16}{'표시명':<18}{'관리자':<8}{'상태':<8}{'방':<6}{'질문':<6}")
        for u in users:
            rooms = await db.scalar(
                select(func.count()).select_from(Room).where(Room.user_id == u.id)
            )
            msgs = await db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.user_id == u.id, Message.role == "user")
            )
            state = "활성" if u.is_active else "차단"
            print(f"{u.username:<16}{u.display_name:<18}{'예' if u.is_admin else '-':<8}"
                  f"{state:<8}{rooms:<6}{msgs:<6}")
    return 0


async def _find(db, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == normalize(username)))


async def cmd_rename(old: str, new: str) -> int:
    async with SessionLocal() as db:
        user = await _find(db, old)
        if user is None:
            print(f"'{old}' 을(를) 찾을 수 없습니다.")
            return 1
        if await _find(db, new):
            print(f"'{new}' 은(는) 이미 있습니다.")
            return 1
        user.username = normalize(new)
        user.display_name = new.strip()
        await db.commit()
        print(f"'{old}' -> '{new}' 로 바꿨습니다. 대화와 통계는 그대로 따라갑니다.")
    return 0


async def cmd_set_active(username: str, active: bool) -> int:
    async with SessionLocal() as db:
        user = await _find(db, username)
        if user is None:
            print(f"'{username}' 을(를) 찾을 수 없습니다.")
            return 1
        user.is_active = active
        await db.commit()
        print(f"'{username}' {'로그인 허용' if active else '로그인 차단'}. 대화는 그대로 있습니다.")
    return 0


async def cmd_admin(username: str) -> int:
    async with SessionLocal() as db:
        user = await _find(db, username)
        if user is None:
            print(f"'{username}' 을(를) 찾을 수 없습니다.")
            return 1
        user.is_admin = True
        await db.commit()
        print(f"'{username}' 을(를) 관리자로 지정했습니다.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]

    if cmd == "list":
        return asyncio.run(cmd_list())
    if cmd == "rename" and len(rest) == 2:
        return asyncio.run(cmd_rename(rest[0], rest[1]))
    if cmd == "disable" and len(rest) == 1:
        return asyncio.run(cmd_set_active(rest[0], False))
    if cmd == "enable" and len(rest) == 1:
        return asyncio.run(cmd_set_active(rest[0], True))
    if cmd == "admin" and len(rest) == 1:
        return asyncio.run(cmd_admin(rest[0]))

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
