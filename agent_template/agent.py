"""★ 개발자가 수정하는 유일한 파일 ★

여기에 내 업무 로직을 쓴다. 규칙은 세 가지뿐이다.

  1. run() 은 이벤트를 yield 하는 async 제너레이터다.
  2. 마지막에 반드시 result(markdown) 를 yield 한다. markdown 형식으로 쓴다.
  3. 예외는 그냥 던져도 된다. main.py 가 error 이벤트로 바꿔준다.

업무 DB(오라클/PostgreSQL) 접근은 각자 자유롭게 구현한다. 이 템플릿은 강제하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import llm
from contract import Event, InvokeRequest, delta, result, status

# 프롬프트는 코드가 아니라 파일로 관리한다. 고치고 서버만 다시 띄우면 반영된다.
SYSTEM_PROMPT = Path("prompt.md").read_text(encoding="utf-8")


async def fetch_business_data(query: str) -> str:
    """TODO: 여기에 내 업무 데이터 조회를 구현한다.

    예) 오라클/PostgreSQL 조회, 사내 API 호출, 파일 읽기 등.
    LLM 이 읽을 수 있도록 문자열(가급적 markdown 표)로 돌려주면 뒤가 편하다.
    """
    return "(아직 업무 데이터 조회가 구현되지 않았습니다. agent.py 의 fetch_business_data 를 채우세요.)"


def build_prompt(req: InvokeRequest, data: str) -> str:
    """LLM 에게 줄 프롬프트를 조립한다. 대화 맥락과 앞 단계 결과를 함께 넣는다."""
    parts: list[str] = []

    # 순차 호출일 때 앞 에이전트가 만든 결과 (없으면 비어 있다)
    for up in req.upstream:
        parts.append(f"## 앞 단계 '{up.agent_id}' 의 결과\n{up.markdown}")

    # 최근 대화 맥락 (코어가 잘라서 넘겨준다)
    if req.context:
        history = "\n".join(f"- {t.role}: {t.content}" for t in req.context)
        parts.append(f"## 최근 대화\n{history}")

    parts.append(f"## 조회한 업무 데이터\n{data}")
    parts.append(f"## 사용자 질문\n{req.query}")
    return "\n\n".join(parts)


async def run(req: InvokeRequest) -> AsyncIterator[Event]:
    """에이전트 본체."""
    yield status("업무 데이터 조회 중")
    data = await fetch_business_data(req.query)

    yield status("응답 작성 중")
    # 매 호출마다 prepare() 를 부른다. 프롬프트 길이에 맞춰 num_ctx 가 다시 계산된다.
    call = llm.prepare(build_prompt(req, data), model=req.model, system=SYSTEM_PROMPT)
    async for token in call.stream():
        yield delta(token)

    yield result(call.text, **call.meta())

    # --- 이미지나 파일을 함께 돌려주고 싶다면 -------------------------------
    # from files import save_bytes
    # att = save_bytes(png_bytes, "매출차트.png")
    # markdown 안에서 attachment:<att.file> 로 참조하면 코어가 실제 URL 로 바꿔준다.
    #
    #   yield result(
    #       f"{call.text}\n\n![매출차트](attachment:{att.file})",
    #       attachments=[att],
    #       **call.meta(),
    #   )
    #
    # 이미지가 아닌 파일(xlsx, pdf 등)은 markdown 에서 참조하지 않아도 된다.
    # 화면 아래에 다운로드 링크로 자동 표시된다.
