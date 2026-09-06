"""라우터가 무엇을 받았는지 파일에 남긴다.

폐쇄망에서 "JSON 파싱 실패" 가 계속 나면 콘솔만으로는 원인을 알 수 없다. 로그가
300자에서 잘리고, 화면을 닫으면 사라지고, 남에게 보여주려면 스크롤해서 긁어야 한다.

그래서 **응답 원문을 통째로** 파일에 남긴다. 성공은 한 줄, 실패는 한 덩어리다.
그래야 "매번 실패인지, 가끔인지" 와 "무엇이 나왔길래 실패했는지" 를 함께 볼 수 있다.

읽을 때는 `python scripts/router_log.py` 를 쓴다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.config import settings

log = logging.getLogger("router_log")

SEP = "=" * 78
# 파일이 무한정 커지지 않게 이 크기를 넘으면 .old 로 밀어낸다.
MAX_BYTES = 5 * 1024 * 1024


def diagnose(text: str) -> str:
    """왜 못 읽었는지 한 줄로. 로그만 보고도 짐작이 가야 한다."""
    from core.graph import _json_candidates, _THINK

    if text is None:
        return "응답이 없음 (None)"
    if not text.strip():
        return "빈 응답 - 모델이 아무것도 내놓지 않았다 (num_predict 가 너무 작거나 모델이 멈춤)"

    cleaned = _THINK.sub(" ", text)
    if "<think" in text.lower() and "</think" not in text.lower():
        return "생각 블록(<think>)이 닫히지 않은 채 끝났다 - 응답이 잘렸을 가능성"
    chunks = _json_candidates(cleaned)
    if not chunks:
        if "{" in cleaned:
            return "중괄호가 열렸지만 닫히지 않았다 - 응답이 중간에 잘렸다 (MAX_TOKENS 확인)"
        if cleaned.strip().startswith("["):
            return "객체가 아니라 배열을 냈다 - {\"agents\": [...]} 형태여야 한다"
        return "JSON 이 아예 없다 - 모델이 평문으로 답했다 (ROUTER_JSON_FORMAT 확인)"

    import json

    for chunk in chunks:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError as exc:
            return f"JSON 덩어리는 있으나 문법이 깨졌다: {exc}"
        if not isinstance(data, dict):
            return "JSON 이 객체가 아니다 (배열이나 값만 나왔다)"
        if "agents" not in data:
            return f"agents 키가 없다 - 나온 키: {sorted(data)}"
        if not isinstance(data["agents"], list):
            return f"agents 가 배열이 아니다 ({type(data['agents']).__name__})"
    return "알 수 없음"


def _path() -> Path | None:
    if not settings.router_log_path:
        return None
    return Path(settings.router_log_path)


def _write(text: str) -> None:
    path = _path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 너무 커지면 한 번만 밀어낸다. 폐쇄망 서버의 디스크를 채우면 안 된다.
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".old"))
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:  # noqa: BLE001 - 로그를 못 써도 대화는 계속되어야 한다
        log.exception("라우터 로그를 쓰지 못했습니다: %s", path)


def success(model: str, query: str, agents: list[str], ms: int, attempt: int) -> None:
    """성공은 한 줄. 실패율을 알려면 성공도 세어야 한다."""
    _write(
        f"{datetime.now():%m-%d %H:%M:%S} OK    model={model} {ms}ms "
        f"try={attempt} agents={agents or '없음'} q={query[:40]!r}\n"
    )


def failure(
    *,
    model: str,
    query: str,
    prompt: str,
    response: str,
    attempt: int,
    retries: int,
    num_ctx: int,
    max_tokens: int,
    json_format: bool,
    ms: int,
) -> None:
    """실패는 한 덩어리. 원문을 **자르지 않고** 남긴다.

    구분선은 덩어리 앞에만 둔다. 머리와 몸통 사이에 넣으면 파일을 구분선으로 잘랐을 때
    한 건이 두 조각으로 나뉘어, 요약이 원인을 찾지 못한다.
    """
    body = (
        f"\n{SEP}\n"
        f"{datetime.now():%Y-%m-%d %H:%M:%S}  라우터 JSON 파싱 실패 "
        f"({attempt}/{retries}회차)\n"
        f"model            : {model}\n"
        f"ROUTER_JSON_FORMAT: {json_format}\n"
        f"num_ctx / max_tokens: {num_ctx} / {max_tokens}\n"
        f"소요             : {ms}ms\n"
        f"질문             : {query}\n"
        f"프롬프트 길이     : {len(prompt)}자\n"
        f"응답 길이         : {len(response or '')}자\n"
        f"진단             : {diagnose(response)}\n"
        f"--- 응답 원문 (자르지 않음) ---\n"
        f"{response}\n"
        f"--- 여기까지 ---\n"
    )
    _write(body)


def give_up(model: str, query: str, response: str) -> None:
    _write(
        f"\n*** 끝내 실패. 에이전트 없이 직접 답변함. "
        f"model={model} q={query[:60]!r}\n"
    )


def prompt_once(prompt: str) -> None:
    """라우터 프롬프트 전문. 코어가 뜬 뒤 처음 실패했을 때 한 번만 남긴다.

    매번 남기면 파일이 같은 내용으로 뒤덮인다. 하지만 한 번은 있어야 한다 —
    프롬프트 자체가 문제일 수도 있기 때문이다.
    """
    global _prompt_logged
    if _prompt_logged:
        return
    _prompt_logged = True
    _write(
        f"\n{SEP}\n[참고] 라우터에게 보낸 프롬프트 전문 (코어 기동 후 1회만 기록)\n"
        f"{SEP}\n{prompt}\n{SEP}\n"
    )


_prompt_logged = False
