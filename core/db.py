"""PostgreSQL 연결. 대화/스케줄 저장용. (요구사항 4)"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from core.models import Base

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """테이블이 없으면 만든다. 스키마가 단순해서 마이그레이션 도구는 쓰지 않는다."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """FastAPI 의존성. 요청 하나당 세션 하나."""
    async with SessionLocal() as session:
        yield session
