"""에이전트 서버 - 계약 고정부. **이 파일은 수정하지 않는다.**

업무 로직은 agent.py 의 run() 에만 쓴다. 이 파일은 계약(4개 엔드포인트)과
스트림 규칙(마지막 줄은 반드시 result 또는 error)을 대신 지켜주는 껍데기다.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

import agent
import files
from contract import (
    CONTRACT_VERSION,
    TERMINAL_TYPES,
    Health,
    InvokeRequest,
    Manifest,
    ResultEvent,
    error,
    to_ndjson,
)

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("agent")

# manifest.yaml 이 이 에이전트의 자기소개다. 코드가 아니라 파일로 관리한다.
with open(os.getenv("MANIFEST_PATH", "./manifest.yaml"), encoding="utf-8") as f:
    MANIFEST = Manifest(contract_version=CONTRACT_VERSION, **yaml.safe_load(f))

# .env 의 AGENT_MODEL. 값이 있으면 화면에서 무엇을 고르든 이 모델로 돈다.
#
# 에이전트는 각자 자기 노트북의 Ollama 를 부르므로, 화면 목록(코어의 Ollama)에 있는
# 모델이 내 노트북에는 없을 수 있다. 그대로 두면 'model not found' 로 나만 빠진다.
# 내 노트북에 확실히 있는 모델을 여기 적어두면 그런 일이 없다.
# 비워두면 화면에서 고른 모델을 그대로 쓴다(기본값).
FORCED_MODEL = os.getenv("AGENT_MODEL", "").strip()
MANIFEST.model = FORCED_MODEL or None


@asynccontextmanager
async def lifespan(_: FastAPI):
    removed = files.cleanup_expired()
    log.info(
        "agent '%s' 기동. 모델 %s, 만료 첨부파일 %d개 정리",
        MANIFEST.id, FORCED_MODEL or "(화면에서 고른 것)", removed,
    )
    yield


app = FastAPI(title=MANIFEST.name, version=CONTRACT_VERSION, lifespan=lifespan)


@app.get("/manifest", response_model=Manifest)
async def get_manifest() -> Manifest:
    return MANIFEST


@app.get("/health", response_model=Health)
async def get_health() -> Health:
    return Health(agent_id=MANIFEST.id)


@app.get("/files/{file_name}")
async def get_file(file_name: str):
    """첨부파일 다운로드. 브라우저가 아니라 코어가 프록시로 호출한다."""
    path = files.resolve(file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type=files.mime_of(path))


def _readable_error(exc: Exception, model: str):
    """오류를 사람이 읽고 조치할 수 있는 문장으로 바꾼다.

    특히 '모델이 없다' 는 이 구조에서 가장 자주 만나게 될 오류다. 에이전트는 각자
    자기 노트북의 Ollama 를 부르는데 모델 목록은 코어 것을 보고 고르기 때문이다.
    원문만 던지면 받는 사람은 무엇을 해야 할지 알 수 없다.
    """
    text = str(exc)
    if "not found" in text and "model" in text.lower():
        return error(
            f"이 노트북의 Ollama 에 '{model}' 모델이 없습니다. "
            f"`ollama pull {model}` 로 받거나, .env 의 AGENT_MODEL 에 "
            f"이 노트북에 있는 모델을 적어 고정하세요.",
            code="MODEL_NOT_FOUND",
        )
    return error(f"{type(exc).__name__}: {text}")


async def _guarded_events(req: InvokeRequest) -> AsyncIterator[str]:
    """agent.run() 을 감싸 계약을 강제한다.

    - result/error 가 나오면 거기서 스트림을 끝낸다 (종료 이벤트는 정확히 하나)
    - 예외가 새어 나오면 error 이벤트로 바꾼다 (한 에이전트의 실패가 전체를 죽이면 안 됨)
    - 종료 이벤트 없이 끝나면 NO_RESULT 오류로 알려준다
    """
    started = time.monotonic()
    # 고정 모델이 있으면 여기서 갈아 끼운다. agent.py 는 req.model 만 보면 되고
    # 개발자가 따로 신경 쓸 일이 없다.
    if FORCED_MODEL:
        req.model = FORCED_MODEL
    try:
        async for event in agent.run(req):
            if isinstance(event, ResultEvent):
                # 개발자가 신경쓰지 않아도 되도록 공통 메타는 여기서 채운다.
                event.meta.setdefault("elapsed_ms", int((time.monotonic() - started) * 1000))
                event.meta.setdefault("agent_id", MANIFEST.id)
            yield to_ndjson(event)
            if event.type in TERMINAL_TYPES:
                return
    except Exception as exc:  # noqa: BLE001 - 어떤 예외든 계약 형식으로 바꿔서 내보낸다
        log.exception("agent.run 실패 request_id=%s", req.request_id)
        yield to_ndjson(_readable_error(exc, req.model))
        return

    # 여기까지 왔다는 건 run() 이 종료 이벤트 없이 끝났다는 뜻이다.
    yield to_ndjson(error("에이전트가 result 를 내보내지 않았습니다", code="NO_RESULT"))


@app.post("/invoke")
async def invoke(req: InvokeRequest):
    """stream=True 면 NDJSON 청크 스트림, False 면 종료 이벤트 하나를 일반 JSON 으로 반환."""
    log.info(
        "invoke id=%s room=%s model=%s q=%.40s",
        req.request_id, req.room_id, FORCED_MODEL or req.model, req.query,
    )

    if req.stream:
        return StreamingResponse(
            _guarded_events(req),
            media_type="application/x-ndjson",
            # 중간 프록시가 버퍼링해서 스트리밍이 끊기지 않도록 알려준다.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 비스트리밍: 마지막(종료) 이벤트만 뽑아서 돌려준다.
    last = "{}"
    async for line in _guarded_events(req):
        last = line
    return json.loads(last)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("AGENT_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_PORT", 9001)),
    )
