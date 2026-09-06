"""예제 에이전트 2 - 앞 단계 결과를 요약한다. (순차 호출 확인용)

업무 DB 없이 LLM 만 쓰는 에이전트가 어떻게 생겼는지 보여준다.
upstream 이 비어 있으면(단독/병렬 호출) 사용자의 질문 자체를 대상으로 요약한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import llm
from contract import Event, InvokeRequest, delta, result, status

SYSTEM_PROMPT = Path("prompt.md").read_text(encoding="utf-8")


async def run(req: InvokeRequest) -> AsyncIterator[Event]:
    # 순차 호출이면 앞 에이전트의 결과가 upstream 으로 들어온다.
    if req.upstream:
        target = "\n\n".join(f"### {u.agent_id}\n{u.markdown}" for u in req.upstream)
        yield status(f"앞 단계 결과 {len(req.upstream)}건 요약 중")
    else:
        target = req.query
        yield status("질문 내용 요약 중")

    prompt = f"## 요약할 내용\n{target}\n\n## 사용자 질문\n{req.query}"
    call = llm.prepare(prompt, model=req.model, system=SYSTEM_PROMPT, max_tokens=512)
    async for token in call.stream():
        yield delta(token)

    yield result(call.text, **call.meta())
