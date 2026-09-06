"""질문 묶기 검증 - 같은 질문은 묶이고 다른 질문은 안 묶이는지.

    python scripts/test_similar.py

한국어는 차이가 말끝에 몰려 있어서 글자 유사도만 보면 엉뚱하게 묶인다.
그 경계를 지키는지 확인하는 것이 이 검사의 목적이다.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.similar import group_questions, normalize  # noqa: E402

passed = failed = 0
NOW = datetime.datetime.now()


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [OK  ] {name}" + (f"  -> {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {name}" + (f"  -> {detail}" if detail else ""))


def q(text, model="gemma4:31b-cloud", ms=600, agents=("echo",)):
    return {
        "text": text,
        "model": model,
        "agents": list(agents),
        "elapsed_ms": ms,
        "created_at": NOW,
    }


def same(a: str, b: str) -> bool:
    """두 문장이 한 묶음이 되는지."""
    groups = group_questions([q(a), q(b)], threshold=0.8)
    return len(groups) == 1


def main() -> int:
    print("\n[1] 같은 질문으로 묶여야 하는 것")
    for a, b in [
        ("지점별 매출 알려줘", "지점별 매출 알려주세요"),
        ("지점별 매출 알려줘", "지점별 매출 알려 줘!"),
        ("이번 달 매출 표로 보여줘", "이번달 매출 표로 보여주세요"),
        ("재고 현황 알려줘", "재고현황 알려줘"),
        ("오늘 상태 점검해줘", "오늘 상태 점검 해주세요"),
    ]:
        check(f"{a!r} = {b!r}", same(a, b))

    print("\n[2] 다른 질문으로 갈려야 하는 것")
    for a, b in [
        ("매출 올려줘", "매출 내려줘"),  # 뜻이 반대
        ("지점별 매출 알려줘", "지점별 재고 알려줘"),  # 대상이 다름
        ("이번 달 매출", "지난 달 매출"),  # 기간이 다름
        ("서울점 매출 알려줘", "부산점 매출 알려줘"),  # 지점이 다름
    ]:
        check(f"{a!r} ≠ {b!r}", not same(a, b))

    print("\n[3] 어미 정리")
    for text, expect in [
        ("지점별 매출 알려줘", "지점별매출알려"),
        ("지점별 매출 알려주세요", "지점별매출알려"),
        ("지점별 매출 보여줘!", "지점별매출보여"),
    ]:
        got = normalize(text)
        check(f"{text!r} -> {got!r}", got == expect, f"기대 {expect!r}")

    print("\n[4] 묶음 요약")
    items = [
        q("지점별 매출 알려줘"),
        q("지점별 매출 알려줘"),
        q("지점별 매출 알려주세요"),
        q("지점별 매출 알려줘", model="gpt-oss:20b-cloud", ms=2400),
        q("재고 현황 알려줘", agents=("stock",)),
    ]
    groups = group_questions(items, threshold=0.8)
    top = groups[0]
    check("가장 많이 물은 것이 맨 앞", top["count"] == 4, f'{top["question"]!r} {top["count"]}회')
    check("표현 가짓수를 센다", top["variants"] == 2, f'{top["variants"]}가지')
    check("모델별로 갈라 보여준다", len(top["models"]) == 2, str([m["model"] for m in top["models"]]))
    fast = min(top["models"], key=lambda m: m["avg_ms"])
    check("모델 속도 비교 가능", fast["avg_ms"] == 600, f'{fast["model"]} {fast["avg_ms"]}ms')
    check("다른 질문은 따로", len(groups) == 2, f"{len(groups)}묶음")

    print("\n[5] 빈 값에도 죽지 않는다")
    check("빈 목록", group_questions([], threshold=0.8) == [])
    check("빈 문자열만", group_questions([q("")], threshold=0.8) == [])

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
