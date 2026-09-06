"""Ollama 호출 공용 모듈 - num_ctx 를 프롬프트 길이에 맞춰 동적으로 잡는다.

SYNC: 원본은 core/llm.py 이고 agent_template/llm.py 는 그 복사본이다.
      (`python scripts/sync_contract.py` 로 맞춘다)
      복사해서 써야 하므로 core.config 같은 상위 모듈을 import 하지 않고 os.environ 만 읽는다.

사용법:
    call = prepare("프롬프트", model=req.model, system="너는 ...")
    async for token in call.stream():
        yield delta(token)
    yield result(call.text, **call.meta())
"""

from __future__ import annotations

import math
import os
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from langchain_ollama import ChatOllama

# .env 를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다.
load_dotenv()


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, default))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


def calc_num_ctx(prompt_chars: int, max_tokens: int) -> int:
    """프롬프트 길이 + 응답 길이로 num_ctx 를 계산한다. (요구사항 14)

    Ollama 에는 믿을 만한 토큰 계산 API 가 없어서 문자 수 기반으로 추정한다.
    한글은 대략 1토큰 = 2글자라 CHARS_PER_TOKEN 기본값을 2.0 으로 둔다.
    추정이 빗나가도 잘리지 않도록 여유분(NUM_CTX_MARGIN)을 더하고 1024 배수로 올린다.
    """
    chars_per_token = _env_float("CHARS_PER_TOKEN", 2.0)
    margin = _env_int("NUM_CTX_MARGIN", 512)
    ctx_min = _env_int("NUM_CTX_MIN", 2048)
    ctx_max = _env_int("NUM_CTX_MAX", 32768)

    estimated = prompt_chars / chars_per_token + max_tokens + margin
    rounded = int(math.ceil(estimated / 1024) * 1024)
    return max(ctx_min, min(rounded, ctx_max))


def _keep_alive() -> str | int:
    """OLLAMA_KEEP_ALIVE_MIN 을 Ollama 가 아는 형식으로 바꾼다.

    분 단위로 받는다. 음수면 계속 올려두고(-1), 0 이면 응답 직후 내린다.
    """
    minutes = _env_int("OLLAMA_KEEP_ALIVE_MIN", 10)
    if minutes < 0:
        return -1
    return f"{minutes}m"


class LlmCall:
    """LLM 호출 한 건. num_ctx 계산 결과와 누적 응답을 함께 들고 있는다."""

    def __init__(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
        **options: Any,
    ) -> None:
        self.prompt = prompt
        self.system = system
        self.model = model or os.getenv("DEFAULT_MODEL", "gemma4:31b-cloud")
        self.max_tokens = max_tokens or _env_int("MAX_TOKENS", 2048)
        # system 도 컨텍스트를 먹으므로 길이 계산에 포함한다.
        self.num_ctx = calc_num_ctx(len(prompt) + len(system or ""), self.max_tokens)
        self.text = ""  # 스트리밍으로 받은 전체 응답이 여기 쌓인다

        self._llm = ChatOllama(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=self.model,
            num_ctx=self.num_ctx,
            num_predict=self.max_tokens,
            temperature=options.pop("temperature", _env_float("LLM_TEMPERATURE", 0.2)),
            # 모델을 얼마나 올려둘지. Ollama 기본은 5분이라, 띄엄띄엄 쓰는 팀 도구에서는
            # 다음 질문이 모델을 통째로 다시 올리는 시간을 문다. "가끔 유독 느리다" 의
            # 흔한 원인이라 .env 로 뺐다.
            keep_alive=_keep_alive(),
            client_kwargs={"timeout": _env_int("LLM_TIMEOUT_S", 300)},
            **options,
        )

    def _messages(self) -> list[tuple[str, str]]:
        msgs: list[tuple[str, str]] = []
        if self.system:
            msgs.append(("system", self.system))
        msgs.append(("human", self.prompt))
        return msgs

    async def stream(self) -> AsyncIterator[str]:
        """토큰을 하나씩 흘려보낸다. 동시에 self.text 에 누적한다."""
        async for chunk in self._llm.astream(self._messages()):
            token = str(chunk.content)
            if token:
                self.text += token
                yield token

    async def invoke(self) -> str:
        """한 번에 전체 응답을 받는다. (스케줄 실행처럼 스트리밍이 필요없을 때)"""
        message = await self._llm.ainvoke(self._messages())
        self.text = str(message.content)
        return self.text

    def meta(self) -> dict[str, Any]:
        """result 이벤트의 meta 로 실어 보낼 값. num_ctx 추정 보정에 쓴다."""
        return {"model": self.model, "num_ctx": self.num_ctx, "max_tokens": self.max_tokens}


def prepare(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int | None = None,
    **options: Any,
) -> LlmCall:
    """LlmCall 을 만든다. 매 호출마다 새로 만들어야 num_ctx 가 프롬프트에 맞게 잡힌다."""
    return LlmCall(prompt, model=model, system=system, max_tokens=max_tokens, **options)
