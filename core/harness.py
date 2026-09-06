"""소프트 하네스 - 판단 규칙을 코드가 아니라 파일(md/yaml)로 관리한다. (요구사항 10/11)

- prompts/*.md : 코디네이터 LLM 에게 주는 지시문 (라우팅, 통합, 직접 답변)
- skills/*.md  : 여러 프롬프트가 공통으로 끼워 쓰는 규칙 조각 (출력 형식 등)
- workflows/*.yaml : 라우팅 없이 정해진 순서로 도는 고정 파이프라인

파일을 고치면 다음 호출부터 바로 반영된다(수정 시각을 보고 다시 읽는다).
프롬프트 문자열을 파이썬 코드에 넣지 않는 이유가 이것이다.

워크플로우는 화면에서도 만들고 고칠 수 있으므로 파일을 쓰는 함수도 여기 둔다.
하네스 파일에 손대는 코드를 이 모듈 밖으로 흩뜨리지 않기 위해서다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from core.config import settings

log = logging.getLogger("harness")

# 경로 -> (수정시각, 내용) 캐시
_cache: dict[Path, tuple[float, str]] = {}


def _read(path: Path) -> str:
    """파일을 읽되, 수정되지 않았으면 캐시를 쓴다."""
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    _cache[path] = (mtime, text)
    return text


def prompt(name: str, **values: Any) -> str:
    """prompts/<name>.md 를 읽고 {키} 자리를 값으로 채운다."""
    text = _read(Path(settings.prompts_dir) / f"{name}.md")
    return text.format(**values) if values else text


def skill(name: str) -> str:
    """skills/<name>.md 를 읽는다. 프롬프트에 끼워 넣는 공통 규칙."""
    return _read(Path(settings.skills_dir) / f"{name}.md")


def list_workflows() -> list[dict[str, Any]]:
    """workflows/*.yaml 전부를 읽어 목록으로 돌려준다."""
    directory = Path(settings.workflows_dir)
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            text = _read(path)
            data = yaml.safe_load(text) or {}
            data["key"] = path.stem
            data["mtime"] = _mtime_ms(path)
            # 맨 윗줄에 서버가 남긴 수정 이력이 있으면 화면에 그대로 보여준다.
            first = text.splitlines()[0] if text.strip() else ""
            data["updated"] = (
                first[len(STAMP_PREFIX):].strip() if first.startswith(STAMP_PREFIX) else ""
            )
            items.append(data)
        except Exception:  # noqa: BLE001 - 워크플로우 하나가 깨져도 나머지는 살린다
            log.exception("워크플로우 로드 실패: %s", path)
    return items


def get_workflow(key: str) -> dict[str, Any] | None:
    return next((w for w in list_workflows() if w["key"] == key), None)


# ---------------------------------------------------------------------------
# 워크플로우 파일 쓰기 - 화면(다이얼로그)에서 등록/수정/삭제할 때 쓴다.
# ---------------------------------------------------------------------------

# 워크플로우 key 는 그대로 파일명이 되므로 슬러그만 허용한다.
# contract.is_safe_file_name 은 첨부파일용이라 공백·점·유니코드를 통과시킨다.
# 여기서는 우리가 이름을 만드는 쪽이므로 더 좁게 잡는 편이 안전하다.
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")

# 저장할 때 서버가 갈아 끼우는 맨 윗줄. 주석이라 yaml 에는 영향이 없다.
STAMP_PREFIX = "# 마지막 수정:"

MODES = ("parallel", "sequential")


class WorkflowError(Exception):
    """워크플로우 파일 조작 실패. 라우터가 그대로 메시지로 내보낸다."""


def workflow_path(key: str) -> Path:
    """key 를 파일 경로로 바꾼다. 디렉터리를 벗어나면 거부한다."""
    if not KEY_RE.match(key or ""):
        raise WorkflowError(
            "이름은 영문 소문자·숫자·하이픈만 쓸 수 있고 50자를 넘을 수 없습니다."
        )
    directory = Path(settings.workflows_dir).resolve()
    path = (directory / f"{key}.yaml").resolve()
    # 심볼릭 링크로 밖을 가리키는 경우까지 막는 이중 방어.
    if path.parent != directory:
        raise WorkflowError("워크플로우 폴더를 벗어날 수 없습니다.")
    return path


def _mtime_ms(path: Path) -> int:
    """수정 시각을 밀리초 정수로. 동시 편집 감지에만 쓰므로 이 정도면 충분하다."""
    return int(path.stat().st_mtime * 1000)


def read_workflow_source(key: str) -> tuple[str, int]:
    """파일 원문과 수정 시각을 그대로 돌려준다. 화면 편집기가 이것을 띄운다."""
    path = workflow_path(key)
    if not path.is_file():
        raise WorkflowError("없는 워크플로우입니다.")
    return path.read_text(encoding="utf-8"), _mtime_ms(path)


def stamp(text: str, editor: str) -> str:
    """맨 윗줄의 수정 이력을 지금 것으로 갈아 끼운다(없으면 새로 넣는다)."""
    lines = text.splitlines()
    if lines and lines[0].startswith(STAMP_PREFIX):
        lines = lines[1:]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "\n".join(lines).lstrip("\n")
    return f"{STAMP_PREFIX} {editor} · {now}\n{body}".rstrip() + "\n"


def write_workflow_source(key: str, text: str, base_mtime: int | None, editor: str) -> int:
    """파일을 쓴다. base_mtime 이 None 이면 신규 생성이다.

    base_mtime 은 편집기가 파일을 열 때 받아간 값이다. 지금 값과 다르면 그 사이에
    다른 사람이 고친 것이므로 덮어쓰지 않는다. 공용 파일이라 실제로 일어난다.
    """
    path = workflow_path(key)
    exists = path.is_file()
    if base_mtime is None and exists:
        raise WorkflowError("같은 이름의 워크플로우가 이미 있습니다.")
    if base_mtime is not None:
        if not exists:
            raise WorkflowError("없는 워크플로우입니다.")
        if _mtime_ms(path) != base_mtime:
            raise WorkflowError("다른 사람이 먼저 고쳤습니다. 창을 닫고 다시 열어주세요.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stamp(text, editor), encoding="utf-8")
    _cache.pop(path, None)  # 다음 읽기가 확실히 새 내용을 보게 한다
    return _mtime_ms(path)


def delete_workflow_file(key: str) -> None:
    path = workflow_path(key)
    if not path.is_file():
        raise WorkflowError("없는 워크플로우입니다.")
    path.unlink()
    _cache.pop(path, None)


def validate_workflow_source(text: str) -> dict[str, Any]:
    """원문을 검사한다. 편집 중 미리보기와 저장 직전 검사가 이 함수 하나를 함께 쓴다.

    두 곳이 서로 다른 규칙을 쓰면 "화면은 통과인데 저장이 거부되는" 일이 생긴다.
    오류가 하나라도 있으면 저장을 막고, 경고는 알려만 주고 저장은 허용한다.
    """
    from core.registry import registry  # 순환 import 를 피해 함수 안에서 가져온다

    errors: list[str] = []
    warnings: list[str] = []
    preview: dict[str, Any] = {"name": "", "mode": "sequential", "steps": []}

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{mark.line + 1}번째 줄: " if mark else ""
        return {"valid": False, "errors": [f"{where}yaml 형식이 아닙니다."],
                "warnings": [], "preview": preview}

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["맨 위는 name/mode/steps 를 담은 목록이어야 합니다."],
                "warnings": [], "preview": preview}

    name = data.get("name")
    if not name:
        warnings.append("name 이 없습니다. 화면에는 파일 이름이 대신 표시됩니다.")
    if not data.get("description"):
        warnings.append("description 이 없습니다. 다른 사람이 용도를 알기 어렵습니다.")

    mode = data.get("mode", "sequential")
    if mode not in MODES:
        errors.append(f"mode 는 {' 또는 '.join(MODES)} 여야 합니다. 지금은 '{mode}' 입니다.")
        mode = "sequential"

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps 에 최소 한 단계가 있어야 합니다.")
        steps = []

    for i, step in enumerate(steps, start=1):
        agent_id = step.get("agent") if isinstance(step, dict) else None
        if not agent_id:
            errors.append(f"{i}번째 단계에 agent 가 없습니다.")
            continue
        info = registry.get(agent_id)
        if info is None:
            # registry.yaml 에 없으면 영영 부를 수 없다. 경고가 아니라 오류다.
            # '에이전트는/가' 로 받아야 id 의 끝소리와 무관하게 문장이 어색해지지 않는다.
            errors.append(
                f"{i}번째 단계의 '{agent_id}' 에이전트는 registry.yaml 에 없습니다."
            )
            continue
        if not info.online:
            # 담당자 노트북이 잠깐 꺼져 있을 뿐일 수 있으므로 저장은 막지 않는다.
            warnings.append(f"'{agent_id}' 에이전트가 지금 오프라인입니다.")
        preview["steps"].append({
            "agent": agent_id,
            "name": info.manifest.name if info.manifest else agent_id,
            "online": info.online,
        })

    preview["name"] = name or ""
    preview["mode"] = mode
    return {"valid": not errors, "errors": errors, "warnings": warnings, "preview": preview}
