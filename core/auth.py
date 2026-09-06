"""로그인 - 이름만 받는다.

**비밀번호를 받지 않는다.** 그러므로 이것은 인증(authentication)이 아니라
신원 표시(identification)다. 남의 이름을 넣으면 그 사람으로 들어올 수 있고,
따라서 "개인 전용 방" 은 보안 경계가 아니라 화면을 어지럽히지 않기 위한 구분이다.
보안 경계는 사내 폐쇄망이 맡는다. 이 파일 밖에서는 이 사실을 몰라도 되게 한다.

나중에 비밀번호가 필요해지면 users 에 컬럼 하나를 추가하고 login() 안에 검증 한 줄만
넣으면 된다. 화면과 다른 API 는 손대지 않아도 된다.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import get_session
from core.models import Room, Session, User

COOKIE_NAME = "agenthub_session"


# ---------------------------------------------------------------------------
# 사용자
# ---------------------------------------------------------------------------


def normalize(username: str) -> str:
    """이름을 다듬는다. 앞뒤 공백과 대소문자 차이로 계정이 갈리지 않게 한다."""
    return username.strip().lower()


async def find_user(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == normalize(username)))


async def create_user(db: AsyncSession, username: str, display_name: str = "") -> User:
    """새 사용자를 만든다. 첫 사용자는 관리자가 되고, 주인 없는 방을 넘겨받는다."""
    is_first = (await db.scalar(select(User.id).limit(1))) is None
    user = User(
        username=normalize(username),
        display_name=display_name.strip() or username.strip(),
        is_admin=is_first,
    )
    db.add(user)
    await db.flush()  # id 를 얻는다

    if is_first:
        # 로그인 도입 전에 만들어진 방들은 주인이 없다. 그대로 두면 개인 전용 규칙 때문에
        # 아무에게도 보이지 않으므로 첫 계정이 넘겨받는다.
        await db.execute(update(Room).where(Room.user_id.is_(None)).values(user_id=user.id))

    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 세션
# ---------------------------------------------------------------------------


async def issue_session(db: AsyncSession, user: User) -> str:
    """세션 토큰을 발급한다. 값은 쿠키로만 오간다."""
    token = secrets.token_urlsafe(32)
    db.add(Session(token=token, user_id=user.id))
    await db.commit()
    return token


async def revoke_session(db: AsyncSession, token: str) -> None:
    session = await db.get(Session, token)
    if session:
        await db.delete(session)
        await db.commit()


async def _resolve(db: AsyncSession, token: str | None) -> User | None:
    """쿠키의 토큰으로 사용자를 찾는다. 만료됐으면 지우고 None."""
    if not token:
        return None
    session = await db.get(Session, token)
    if session is None:
        return None

    deadline = datetime.now(timezone.utc) - timedelta(days=settings.session_ttl_days)
    if session.created_at < deadline:
        await db.delete(session)
        await db.commit()
        return None

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None

    # 마지막 사용 시각은 하루에 한 번만 갱신한다. 매 요청마다 쓰면 낭비다.
    if (datetime.now(timezone.utc) - session.last_seen_at) > timedelta(days=1):
        session.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
    return user


# ---------------------------------------------------------------------------
# FastAPI 의존성
# ---------------------------------------------------------------------------


async def current_user(
    agenthub_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_session),
) -> User:
    """로그인이 필요한 엔드포인트에 건다. 아니면 401."""
    user = await _resolve(db, agenthub_session)
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return user


async def optional_user(
    agenthub_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_session),
) -> User | None:
    """로그인해도 되고 안 해도 되는 곳에 건다."""
    return await _resolve(db, agenthub_session)


def to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
    }
