"""워크플로우 API - 목록 조회와 화면에서의 등록/수정/삭제. (요구사항 11)

워크플로우는 yaml 파일 하나가 곧 정의다. 화면에서도 **원문을 그대로** 보여주고 고친다.
폼으로 감싸면 주석이 사라지고, 파일을 직접 고치는 사람과 화면으로 고치는 사람이
서로 다른 것을 보게 된다.

채팅방과 달리 워크플로우는 전원이 함께 쓰는 공용 파일이다. 그래서
- 누구나 고칠 수 있게 하되 마지막에 고친 사람을 파일 맨 윗줄에 남기고,
- 쓰고 있는 방이 하나라도 있으면 삭제를 거부한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import harness
from core.auth import current_user
from core.config import settings
from core.db import get_session
from core.models import Room, User

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class SourceIn(BaseModel):
    """편집기가 올려보내는 원문."""

    source: str
    # 파일을 열 때 받아간 수정 시각. None 이면 신규 생성이다.
    base_mtime: int | None = None


def _editable() -> None:
    """읽기 전용으로 잠근 환경이면 여기서 막는다."""
    if not settings.workflow_edit_enabled:
        raise HTTPException(status_code=403, detail="이 서버는 워크플로우를 보기만 할 수 있습니다.")


def _fail(exc: harness.WorkflowError, status: int = 400):
    return HTTPException(status_code=status, detail=str(exc))


@router.get("")
async def list_workflows(user: User = Depends(current_user)) -> dict:
    """고정 파이프라인 목록.

    화면에서 고른 워크플로우가 무엇을 어떤 순서로 부르는지 보여줘야 하므로
    steps 와 mode 까지 함께 내려준다.
    """
    items = [
        {
            "key": w["key"],
            "name": w.get("name", w["key"]),
            "description": w.get("description", ""),
            "mode": w.get("mode", "sequential"),
            "steps": [s.get("agent") for s in (w.get("steps") or []) if isinstance(s, dict)],
            "mtime": w.get("mtime"),
            "updated": w.get("updated", ""),
        }
        for w in harness.list_workflows()
    ]
    return {"workflows": items, "editable": settings.workflow_edit_enabled}


@router.get("/{key}/source")
async def get_source(key: str, user: User = Depends(current_user)) -> dict:
    """파일 원문을 그대로 돌려준다. 편집기가 이것을 띄운다."""
    try:
        text, mtime = harness.read_workflow_source(key)
    except harness.WorkflowError as exc:
        raise _fail(exc, 404)
    return {"key": key, "source": text, "mtime": mtime}


@router.post("/validate")
async def validate(body: SourceIn, user: User = Depends(current_user)) -> dict:
    """저장하지 않고 검사만 한다. 편집 중에 호출한다."""
    return harness.validate_workflow_source(body.source)


@router.put("/{key}")
async def save(key: str, body: SourceIn, user: User = Depends(current_user)) -> dict:
    """저장한다. base_mtime 이 없으면 신규 생성이다."""
    _editable()
    check = harness.validate_workflow_source(body.source)
    if not check["valid"]:
        raise HTTPException(status_code=400, detail=" / ".join(check["errors"]))
    try:
        mtime = harness.write_workflow_source(
            key, body.source, body.base_mtime, user.display_name
        )
    except harness.WorkflowError as exc:
        # 이름 충돌과 동시 편집은 409, 형식 문제는 400.
        status = 409 if "이미 있습니다" in str(exc) or "먼저 고쳤습니다" in str(exc) else 400
        raise _fail(exc, status)
    text, _ = harness.read_workflow_source(key)
    return {"key": key, "mtime": mtime, "source": text, "warnings": check["warnings"]}


@router.delete("/{key}")
async def remove(
    key: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """삭제한다. 쓰고 있는 방이 하나라도 있으면 거부한다."""
    _editable()

    rows = (await db.execute(select(Room).where(Room.workflow == key))).scalars().all()
    if rows:
        mine = [r.title for r in rows if r.user_id == user.id]
        others = len(rows) - len(mine)
        # 방은 개인 전용이므로 남의 방 제목은 내리지 않고 개수만 알려준다.
        parts = [f"'{t}'" for t in mine[:3]]
        if others:
            parts.append(f"다른 사람의 방 {others}개")
        raise HTTPException(
            status_code=409,
            detail=f"{len(rows)}개 방이 쓰고 있어 지울 수 없습니다 ({', '.join(parts)}). "
            "그 방들의 워크플로우를 '사용 안 함' 으로 바꾼 뒤 다시 시도하세요.",
        )

    try:
        harness.delete_workflow_file(key)
    except harness.WorkflowError as exc:
        raise _fail(exc, 404)
    return {"key": key, "deleted": True}
