"""로그인 API - 이름만 받는다. (비밀번호 없음)"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import auth
from core.config import settings
from core.db import get_session
from core.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_session)) -> list[dict]:
    """로그인 화면에서 고를 수 있게 이름 목록을 준다.

    비밀번호가 없는 구조이므로 이 목록을 감춰봐야 얻는 것이 없다.
    10명이면 타이핑보다 눌러 고르는 편이 빠르다.
    """
    rows = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.created_at)
    )
    return [{"username": u.username, "display_name": u.display_name} for u in rows]


@router.post("/login")
async def login(
    body: LoginIn, response: Response, db: AsyncSession = Depends(get_session)
) -> dict:
    """이름으로 들어온다. 처음 보는 이름이면 그 자리에서 계정을 만든다."""
    username = auth.normalize(body.username)
    if not username:
        raise HTTPException(status_code=400, detail="이름을 입력하세요")

    user = await auth.find_user(db, username)
    created = False
    if user is None:
        user = await auth.create_user(db, username, display_name=body.username)
        created = True
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="사용할 수 없는 계정입니다")

    token = await auth.issue_session(db, user)
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,  # 자바스크립트가 읽지 못하게 한다
        samesite="lax",
        max_age=settings.session_ttl_days * 24 * 3600,
        path="/",
    )
    return {"user": auth.to_dict(user), "created": created}


@router.post("/logout")
async def logout(
    response: Response,
    agenthub_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    if agenthub_session:
        await auth.revoke_session(db, agenthub_session)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(auth.current_user)) -> dict:
    return auth.to_dict(user)
