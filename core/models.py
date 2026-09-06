"""테이블 정의. 단순하게 5개만 둔다. (요구사항 7)"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# PostgreSQL 이면 JSONB, 아니면 일반 JSON 으로 떨어지게 해둔다.
JsonType = JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    """사용자. 비밀번호를 받지 않는다.

    이름만으로 들어오므로 이것은 인증이 아니라 신원 표시다. 보안 경계는 사내망이 맡고
    앱은 "누가 무엇을 썼는지" 만 구분한다. 나중에 비밀번호가 필요해지면 컬럼 하나를
    추가하고 core/auth.py 의 검증 한 줄만 고치면 된다.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # 첫 계정만 true
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """로그인 세션. 토큰을 HttpOnly 쿠키로 내려준다.

    DB 에 두므로 코어를 재기동해도 로그인이 유지되고, 로그아웃이 즉시 반영된다.
    """

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Room(Base):
    """채팅방. 여러 개 만들 수 있다. (요구사항 13)

    user_id 로 주인을 구분해 자기 방만 목록에 보이게 한다.
    """

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # SET NULL 이다. 사용자를 지웠다고 대화까지 사라지면 안 된다.
    # 사람이 팀을 떠날 때는 지우지 말고 is_active 를 끄는 것이 정석이다.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="새 대화")
    model: Mapped[str] = mapped_column(String(100))  # 방마다 모델 선택 (요구사항 18)
    mode: Mapped[str] = mapped_column(String(20), default="parallel")  # parallel | sequential
    workflow: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 고정 파이프라인
    # 사람이 없을 때 스케줄이 남긴 결과의 수. 방을 열어보면 0 으로 돌아간다.
    unread: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # order_by 가 없으면 순서를 보장하지 않는다. 순차 실행은 이 순서가 곧 실행 순서다.
    agents: Mapped[list["RoomAgent"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoomAgent.position",
    )


class RoomAgent(Base):
    """방에서 사용자가 직접 선택해 둔 에이전트. 비어 있으면 라우터 LLM 이 고른다.

    position 은 화면에서 고른 순서다. **순차 실행에서는 이것이 곧 실행 순서**이므로
    버리면 안 된다. 예전에는 이 컬럼이 없어 3개 이상을 고르거나 새로고침하면
    어떤 순서로 도는지 알 수 없었다.
    """

    __tablename__ = "room_agents"

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    room: Mapped[Room] = relationship(back_populates="agents")


class Message(Base):
    """대화 한 줄. 응답은 Markdown 원문 그대로 저장한다. (요구사항 19)"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # 질문한 사람
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | schedule
    content_md: Mapped[str] = mapped_column(Text)
    # 첨부파일 목록, 호출된 에이전트, num_ctx 등 부가 정보
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRun(Base):
    """에이전트 호출 1건의 기록. 누가 느린지/실패하는지 추적용.

    room_id 에 외래키를 걸지 않는다. 방을 지워도 운영 지표는 남아야 하기 때문이다.
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20))  # ok | error
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 에이전트가 실제로 쓴 num_ctx. .env 의 CHARS_PER_TOKEN 추정치를 보정하는 근거가 된다.
    num_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Schedule(Base):
    """방별 스케줄. room_id 를 기본키로 둬서 '방당 1개'를 DB 가 보장한다. (요구사항 16)"""

    __tablename__ = "schedules"

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True
    )
    cron: Mapped[str] = mapped_column(String(100))  # 예: "0 9 * * 1-5" (분 시 일 월 요일)
    prompt: Mapped[str] = mapped_column(Text)  # 시간이 되면 이 질문을 대신 던진다
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
