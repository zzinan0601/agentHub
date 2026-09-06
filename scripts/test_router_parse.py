"""라우터 응답 파싱 검사.

폐쇄망의 12B 모델은 "JSON 만 내라" 는 지시를 자주 어긴다. 설명을 곁들이거나,
코드펜스로 감싸거나, 생각을 먼저 적거나, JSON 을 두 번 낸다.
그런 출력을 실제로 넣어 보고 계획을 뽑아내는지 확인한다.

    python scripts/test_router_parse.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.graph import _extract_json  # noqa: E402

PLAN = {"agents": ["echo"], "mode": "parallel"}

# (설명, 모델이 실제로 내놓을 법한 응답, 기대하는 agents)
CASES: list[tuple[str, str, list[str] | None]] = [
    ("깔끔한 JSON", '{"agents":["echo"],"mode":"parallel","reason":"매출 조회"}', ["echo"]),
    ("코드펜스로 감쌈", '```json\n{"agents":["echo"],"mode":"parallel"}\n```', ["echo"]),
    ("앞에 설명을 붙임", '네, 계획입니다.\n{"agents":["echo"],"mode":"parallel"}', ["echo"]),
    ("뒤에 설명을 붙임", '{"agents":["echo"],"mode":"parallel"}\n이렇게 부르면 됩니다.', ["echo"]),
    ("앞뒤로 다 붙임", '계획:\n{"agents":["echo"]}\n필요하면 말씀하세요.', ["echo"]),
    (
        "생각을 먼저 적음 (중괄호 포함)",
        '<think>매출이면 {echo} 가 맞겠다</think>{"agents":["echo"],"mode":"parallel"}',
        ["echo"],
    ),
    (
        "JSON 을 두 번 냄",
        '{"example":{"agents":["a"]}}\n실제 계획:\n{"agents":["echo"],"mode":"parallel"}',
        ["echo"],
    ),
    (
        "예시를 먼저 보여주고 답함",
        '형식은 {"agents": [...]} 입니다.\n{"agents":["echo","summary"],"mode":"sequential"}',
        ["echo", "summary"],
    ),
    ("빈 배열 (잡담)", '{"agents":[],"mode":"parallel","reason":"인사"}', []),
    ("문자열에 중괄호가 들어감", '{"agents":["echo"],"reason":"표 {행:열} 정리"}', ["echo"]),
    ("줄바꿈이 섞인 JSON", '{\n  "agents": [\n    "echo"\n  ],\n  "mode": "parallel"\n}', ["echo"]),
    # --- 아래는 뽑아낼 수 없는 것이 맞다 ---
    ("JSON 이 아예 없음", "매출 조회 에이전트를 부르면 됩니다.", None),
    ("중괄호가 열리기만 함", '{"agents": ["echo"', None),
]


def main() -> int:
    ok = bad = 0
    for label, text, expected in CASES:
        parsed = _extract_json(text)
        got = parsed.get("agents") if isinstance(parsed, dict) else None
        if got == expected:
            ok += 1
            print(f"  [OK] {label}")
        else:
            bad += 1
            print(f"  [XX] {label}\n       기대 {expected} / 실제 {got}")

    print(f"\n  {ok + bad}개 중 {ok}개 통과")
    if bad:
        return 1

    print(
        "\n  참고: 이 검사는 '섞여 들어온 출력을 견디는가' 만 본다.\n"
        "  애초에 섞이지 않게 하는 것은 .env 의 ROUTER_JSON_FORMAT=true 다.\n"
        "  Ollama 가 디코딩 단계에서 JSON 만 내도록 강제한다."
    )
    return 0


if __name__ == "__main__":
    print("\n라우터 응답 파싱 검사\n")
    sys.exit(main())
