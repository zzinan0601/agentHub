"""에이전트 호출 - 단일 / 병렬 / 순차. (요구사항 15)

에이전트가 흘려보낸 NDJSON 이벤트에 agent_id 를 붙여 그대로 위로 중계한다.
한 에이전트가 실패해도 error 이벤트로 바꿔서 전달할 뿐 전체를 멈추지 않는다.

'사용 중' 표시를 잡고 푸는 곳도 여기다. 단일·병렬·순차·스케줄 어느 쪽에서 불러도
call_agent 하나를 지나므로 빠뜨릴 수가 없고, finally 라서 타임아웃·사망·중단
어느 경우에도 잠금이 남지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from core.config import settings
from core.contract import InvokeRequest, UpstreamResult
from core.registry import AgentInfo, registry

log = logging.getLogger("dispatcher")

# 스트림이 끝났음을 알리는 내부 신호 (병렬 병합에서만 쓴다)
_DONE = object()


async def call_agent(
    agent: AgentInfo, req: InvokeRequest, who: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """에이전트 하나를 호출하고 이벤트를 하나씩 내보낸다. 예외는 error 이벤트가 된다."""
    # 미리 검사했더라도 그 사이 다른 사람이 잡았을 수 있다. 여기가 최종 관문이다.
    if not registry.acquire(agent.id, who):
        yield {
            "type": "error",
            "agent_id": agent.id,
            "code": "AGENT_BUSY",
            "message": f"{agent.id} 를 다른 사람이 쓰고 있어 건너뜁니다",
        }
        return

    timeout = httpx.Timeout(settings.agent_timeout_s, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{agent.url}/invoke", json=req.model_dump()
            ) as res:
                res.raise_for_status()
                # aiter_lines 가 청크 경계를 알아서 처리해준다.
                async for line in res.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("%s: NDJSON 이 아닌 줄을 보냈습니다: %.100s", agent.id, line)
                        continue
                    event["agent_id"] = agent.id
                    if event.get("type") == "result":
                        _apply_attachment_urls(event)
                    yield event
    except Exception as exc:  # noqa: BLE001 - 죽은 에이전트 때문에 대화 전체가 끊기면 안 된다
        log.warning("에이전트 호출 실패 %s: %s", agent.id, exc)
        yield {
            "type": "error",
            "agent_id": agent.id,
            "code": "CALL_FAILED",
            "message": f"{agent.id} 호출 실패: {exc}",
        }
    finally:
        registry.release(agent.id)


def _apply_attachment_urls(event: dict[str, Any]) -> None:
    """첨부파일에 브라우저가 쓸 URL 을 붙이고, markdown 안의 참조를 그 URL 로 바꾼다.

    파일 실물은 에이전트 노트북에 있지만 브라우저는 코어만 바라보게 한다.
    (코어의 /api/files/{agent_id}/{file} 가 에이전트로 프록시한다)
    """
    agent_id = event.get("agent_id", "")
    markdown = event.get("markdown", "")
    for att in event.get("attachments") or []:
        url = f"/api/files/{agent_id}/{att['file']}"
        att["url"] = url
        # agent.py 에서 ![차트](attachment:xxx.png) 로 참조한 것을 실제 URL 로 치환
        markdown = markdown.replace(f"attachment:{att['file']}", url)
    event["markdown"] = markdown


async def _pump(
    agent: AgentInfo, req: InvokeRequest, queue: asyncio.Queue, who: str
) -> None:
    """병렬 호출용. 한 에이전트의 이벤트를 공용 큐에 밀어 넣는다."""
    try:
        async for event in call_agent(agent, req, who):
            await queue.put(event)
    finally:
        await queue.put(_DONE)


async def run_parallel(
    agents: list[AgentInfo], make_req, who: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """여러 에이전트를 동시에 부르고, 먼저 오는 이벤트부터 순서대로 내보낸다."""
    queue: asyncio.Queue = asyncio.Queue()
    tasks = [asyncio.create_task(_pump(a, make_req(a), queue, who)) for a in agents]
    remaining = len(tasks)
    try:
        while remaining:
            item = await queue.get()
            if item is _DONE:
                remaining -= 1
                continue
            yield item
    finally:
        for task in tasks:
            task.cancel()


async def run_sequential(
    agents: list[AgentInfo], make_req, who: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """앞 에이전트의 결과를 다음 에이전트의 upstream 으로 넘기며 차례대로 부른다."""
    upstream: list[UpstreamResult] = []
    for agent in agents:
        req = make_req(agent)
        req.upstream = list(upstream)
        async for event in call_agent(agent, req, who):
            yield event
            if event.get("type") == "result":
                upstream.append(
                    UpstreamResult(agent_id=agent.id, markdown=event.get("markdown", ""))
                )


def resolve(agent_ids: list[str]) -> tuple[list[AgentInfo], list[str]]:
    """id 목록을 실제 에이전트로 바꾼다. 없거나 꺼져 있는 것은 따로 알려준다."""
    found, missing = [], []
    for agent_id in agent_ids:
        agent = registry.get(agent_id)
        if agent and agent.online:
            found.append(agent)
        else:
            missing.append(agent_id)
    return found, missing
