"""에이전트 목록 / 모델 목록 / 첨부파일 프록시.

워크플로우는 등록·수정·삭제까지 있어 routers/workflows.py 로 따로 뺐다.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.config import settings
from core.contract import is_safe_file_name
from core.registry import registry

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents")
async def get_agents() -> list[dict]:
    """호출 가능한 에이전트 목록. 화면 오른쪽에 그대로 표시된다. (요구사항 17)"""
    return [a.to_dict() for a in registry.all()]


@router.post("/agents/refresh")
async def refresh_agents() -> list[dict]:
    """registry.yaml 을 지금 즉시 다시 읽는다. (30초 주기를 기다리지 않을 때)"""
    await registry.refresh()
    return [a.to_dict() for a in registry.all()]


@router.get("/models")
async def get_models() -> dict:
    """Ollama 에 설치된 모델 목록. 화면에서 모델을 고를 수 있게 한다. (요구사항 18)"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{settings.ollama_base_url}/api/tags")
            res.raise_for_status()
            names = sorted(m["name"] for m in res.json().get("models", []))
    except Exception as exc:  # noqa: BLE001 - Ollama 가 꺼져 있어도 화면은 떠야 한다
        return {"models": [settings.default_model], "default": settings.default_model,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"models": names, "default": settings.default_model}


@router.get("/files/{agent_id}/{file_name}")
async def proxy_file(agent_id: str, file_name: str):
    """에이전트 노트북에 있는 첨부파일을 브라우저에 중계한다.

    브라우저가 에이전트를 직접 부르지 않으므로 에이전트마다 CORS 를 열 필요가 없다.
    캐시는 하지 않는다. 해당 에이전트가 꺼져 있으면 파일도 받을 수 없다.
    """
    if not is_safe_file_name(file_name):
        raise HTTPException(status_code=400, detail="invalid file name")
    agent = registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    client = httpx.AsyncClient(timeout=httpx.Timeout(settings.agent_timeout_s, connect=5.0))
    try:
        req = client.build_request("GET", f"{agent.url}/files/{file_name}")
        res = await client.send(req, stream=True)
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"에이전트에 연결할 수 없습니다: {exc}")

    if res.status_code != 200:
        await res.aclose()
        await client.aclose()
        raise HTTPException(status_code=res.status_code, detail="file not found")

    async def _body():
        try:
            async for chunk in res.aiter_bytes():
                yield chunk
        finally:
            await res.aclose()
            await client.aclose()

    headers = {}
    if "content-disposition" in res.headers:
        headers["content-disposition"] = res.headers["content-disposition"]
    return StreamingResponse(
        _body(),
        media_type=res.headers.get("content-type", "application/octet-stream"),
        headers=headers,
    )
