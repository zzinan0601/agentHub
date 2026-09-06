"""예제 에이전트 1 - 계약이 제대로 도는지 확인하는 용도.

LLM 을 쓰지 않고 즉시 결과를 만든다. 그래서 코어/UI/스트리밍/첨부파일을
모델 속도와 무관하게 빠르게 검증할 수 있다.
실제 업무 에이전트를 만들 때는 agent_template/agent.py 를 기준으로 삼는다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import AsyncIterator

from contract import Event, InvokeRequest, delta, result, status
from files import save_text

# 업무 DB 대신 쓰는 가짜 데이터. 실제로는 오라클/PostgreSQL 조회 결과가 들어온다.
ROWS = [
    ("서울점", 1_240_000),
    ("부산점", 980_000),
    ("대구점", 615_000),
]


async def run(req: InvokeRequest) -> AsyncIterator[Event]:
    yield status("매출 데이터 조회 중")
    await asyncio.sleep(0.3)  # DB 조회에 걸리는 시간을 흉내낸다

    yield status("표 만드는 중")
    lines = ["## 지점별 매출", "", "| 지점 | 매출 |", "| --- | ---: |"]
    lines += [f"| {name} | {value:,} |" for name, value in ROWS]
    markdown = "\n".join(lines)

    # 스트리밍이 화면에서 어떻게 보이는지 확인하려고 한 줄씩 흘려보낸다.
    for line in lines:
        yield delta(line + "\n")
        await asyncio.sleep(0.02)

    # 첨부파일 예시: 같은 내용을 CSV 로도 내려받을 수 있게 한다.
    csv = "지점,매출\n" + "\n".join(f"{n},{v}" for n, v in ROWS)
    attachment = save_text(csv, "지점별매출.csv", mime="text/csv; charset=utf-8")

    # 조회 시각 같은 부가 정보는 본문에 넣지 않고 meta 로 넘긴다.
    # 본문에는 사용자가 읽고 복사할 내용만 담는다. (시각은 화면 구석에 따로 표시된다)
    yield result(
        markdown,
        attachments=[attachment],
        source="echo-demo",
        queried_at=f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
    )
