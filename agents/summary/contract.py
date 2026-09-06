"""에이전트 계약(contract) 스키마 - v1.0

개발자 10명이 만드는 모든 에이전트와 코디네이터(core)가 공유하는 유일한 규약이다.

SYNC: 원본은 core/contract.py 이고 agent_template/contract.py 는 그 복사본이다.
      (폐쇄망이라 사내 패키지 인덱스를 쓸 수 없어 공용 라이브러리 대신 복사본으로 관리한다)
      원본을 고쳤으면 `python scripts/sync_contract.py` 로 복사본을 맞추고,
      계약 자체가 바뀌었으면 CONTRACT_VERSION 을 올린다.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

# 계약 버전. 코어는 에이전트 manifest 의 이 값을 검사해 불일치 시 경고를 띄운다.
CONTRACT_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 요청 (코어 -> 에이전트)
# ---------------------------------------------------------------------------


class Turn(BaseModel):
    """대화 한 턴. 코어가 최근 N턴을 잘라서 넘겨준다."""

    role: Literal["user", "assistant"]
    content: str


class UpstreamResult(BaseModel):
    """순차 호출에서 앞 단계 에이전트가 만든 결과."""

    agent_id: str
    markdown: str


class InvokeRequest(BaseModel):
    """모든 에이전트의 POST /invoke 요청 본문. 필드를 임의로 늘리거나 줄이지 않는다."""

    request_id: str  # 추적용 UUID. 로그에 그대로 남긴다.
    room_id: int  # 채팅방 id
    query: str  # 사용자가 입력한 원문
    context: list[Turn] = Field(default_factory=list)  # 최근 대화
    upstream: list[UpstreamResult] = Field(default_factory=list)  # 순차 호출 시 앞 결과
    model: str  # 방에서 선택한 모델. 에이전트는 이 값을 그대로 써야 한다.
    options: dict[str, Any] = Field(default_factory=dict)  # temperature 등 부가 옵션
    stream: bool = True  # False 면 result 이벤트 하나를 일반 JSON 으로 반환


# ---------------------------------------------------------------------------
# manifest (에이전트 -> 코어)
# ---------------------------------------------------------------------------


class Manifest(BaseModel):
    """GET /manifest 응답. 라우터 LLM 이 description 과 examples 를 읽고 판단한다."""

    contract_version: str = CONTRACT_VERSION
    id: str  # registry.yaml 의 id 와 일치해야 한다
    name: str  # 화면에 보일 이름
    description: str  # "무엇을 할 수 있는지" - 라우팅 품질을 좌우하는 핵심 필드
    owner: str  # 담당 개발자
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)  # 이 에이전트를 부를 만한 질문 예시
    # 이 에이전트가 자기 .env(AGENT_MODEL)로 고정해 둔 모델. 없으면 화면에서 고른 것을 쓴다.
    # 에이전트는 각자 자기 노트북의 Ollama 를 부르므로 화면 목록에 있는 모델이 그 노트북에는
    # 없을 수 있다. 고정해 둔 사람이 있으면 화면에 그렇게 표시해 준다.
    model: str | None = None


class Health(BaseModel):
    """GET /health 응답."""

    status: Literal["ok"] = "ok"
    agent_id: str
    contract_version: str = CONTRACT_VERSION


# ---------------------------------------------------------------------------
# 이벤트 (에이전트 -> 코어 -> UI), NDJSON 한 줄 = 이벤트 하나
# ---------------------------------------------------------------------------


class StatusEvent(BaseModel):
    """진행 상황 알림. 몇 개든 보내도 되고 안 보내도 된다."""

    type: Literal["status"] = "status"
    message: str


class DeltaEvent(BaseModel):
    """LLM 토큰 조각. 화면에 이어붙여 표시된다."""

    type: Literal["delta"] = "delta"
    text: str


class Attachment(BaseModel):
    """에이전트가 만든 이미지/파일 한 개.

    파일 실물은 **에이전트 노트북의 디스크**에 남고, 여기에는 파일명만 싣는다.
    브라우저는 에이전트를 직접 부르지 않고 코어의 프록시(/api/files/{agent_id}/{file})
    를 통해 내려받는다. 그래서 에이전트마다 CORS 를 설정할 필요가 없다.

    markdown 안에서는 `![차트](attachment:chart.png)` 처럼 file 이름으로 참조하면
    코어가 실제 URL 로 바꿔준다.
    """

    name: str  # 화면/다운로드에 쓸 이름 (예: 2월매출.xlsx)
    file: str  # 에이전트 files 디렉터리의 파일명. 경로 구분자(/ \ ..) 금지
    mime: str  # image/png, application/pdf 등
    size: int | None = None  # 바이트. 모르면 생략


class ResultEvent(BaseModel):
    """성공 종료. 스트림의 마지막 줄이며 markdown 은 반드시 Markdown 형식이어야 한다."""

    type: Literal["result"] = "result"
    markdown: str
    attachments: list[Attachment] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)  # elapsed_ms, model, num_ctx 등


class ErrorEvent(BaseModel):
    """실패 종료. 예외를 밖으로 던지지 말고 이 이벤트로 바꿔서 내보낸다."""

    type: Literal["error"] = "error"
    message: str
    code: str = "AGENT_ERROR"


Event = StatusEvent | DeltaEvent | ResultEvent | ErrorEvent

# 스트림을 끝내는 이벤트 종류. 이 둘 중 하나가 정확히 한 번, 마지막에 와야 한다.
TERMINAL_TYPES = {"result", "error"}


# ---------------------------------------------------------------------------
# 헬퍼 - agent.py 에서 짧게 쓰라고 제공한다
# ---------------------------------------------------------------------------


def status(message: str) -> StatusEvent:
    return StatusEvent(message=message)


def delta(text: str) -> DeltaEvent:
    return DeltaEvent(text=text)


def result(
    markdown: str, attachments: list[Attachment] | None = None, **meta: Any
) -> ResultEvent:
    return ResultEvent(markdown=markdown, attachments=attachments or [], meta=meta)


def error(message: str, code: str = "AGENT_ERROR") -> ErrorEvent:
    return ErrorEvent(message=message, code=code)


def is_safe_file_name(name: str) -> bool:
    """첨부파일명이 안전한지 검사한다.

    경로 구분자나 상위 디렉터리 참조가 섞이면 남의 파일을 읽어갈 수 있으므로
    에이전트의 /files 라우트와 코어의 프록시 양쪽에서 이 함수로 먼저 거른다.
    """
    return bool(name) and not any(c in name for c in ("/", "\\", "\0")) and ".." not in name


def to_ndjson(event: Event | dict[str, Any]) -> str:
    """이벤트를 NDJSON 한 줄(개행 포함)로 직렬화한다."""
    data = event if isinstance(event, dict) else event.model_dump()
    return json.dumps(data, ensure_ascii=False) + "\n"
