"""비슷한 질문을 하나로 묶는다.

"지점별 매출 알려줘" 와 "지점별 매출 알려주세요" 는 사람이 보기엔 같은 질문이지만
글자로는 다르다. 그대로 세면 자주 묻는 질문이 잘게 쪼개져 아무것도 안 보인다.

표준 라이브러리 difflib 만 쓴다. PostgreSQL 의 pg_trgm 을 쓰면 더 빠르지만
확장 설치가 폐쇄망 반입 절차에 하나 더 얹히므로 쓰지 않는다.

## 글자만 비교하면 안 되는 이유

한국어에서 글자 유사도만 보면 짧은 문장에서 엉뚱하게 걸린다.

    "매출 올려줘"  vs "매출 내려줘"        0.80  ← 뜻이 반대인데 같다고 나온다
    "매출 알려줘"  vs "매출 알려주세요"    0.78  ← 같은 질문인데 다르다고 나온다

두 경우 모두 차이가 **말끝**에 있다. 그래서 비교하기 전에 요청 어미를 먼저 걷어낸다.
그러면 위 두 쌍이 각각 0.75(다름) / 완전 일치(같음) 로 제대로 갈린다.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# 묶음 판정에 방해가 되는 문장부호와 공백
_NOISE = re.compile(r"[\s.,!?~…·\-_'\"()\[\]{}]+")

# 주제를 담지 않는 요청·존대 어미. 긴 것부터 지워야 "주세요" 가 "요" 로 먼저 잘리지 않는다.
_ENDINGS = sorted(
    (
        "해주시겠어요", "해주시겠습니까", "해주세요", "해줄래", "해주라", "해줘",
        "주시겠어요", "주시겠습니까", "주시겠니", "주세요", "주라", "줄래", "줘",
        "부탁해", "부탁드립니다", "부탁합니다",
        "알려주", "보여주",  # "알려주세요" 에서 어미를 뗀 뒤 남는 꼬리
        "입니다", "습니다", "ㅂ니다",
        "인가요", "은가요", "는가요", "나요", "까요", "가요",
        "이에요", "예요", "에요", "어요", "아요", "세요", "지요",
        "인지", "는지", "은지",
    ),
    key=len,
    reverse=True,
)


def normalize(text: str) -> str:
    """비교하기 좋게 다듬는다.

    띄어쓰기·문장부호를 걷어내고, 주제를 담지 않는 요청 어미를 뗀다.
    조사(을/를/은/는)는 건드리지 않는다. 거기까지 손대면 뜻이 다른 질문이
    같은 것으로 묶일 수 있고, 그 정도 차이는 유사도가 알아서 흡수한다.
    """
    cleaned = _NOISE.sub("", text.strip().lower())

    # 어미가 겹쳐 붙는 경우가 있어("알려주세요" -> "알려주" -> "알려") 몇 번 반복한다.
    for _ in range(3):
        for ending in _ENDINGS:
            if cleaned.endswith(ending) and len(cleaned) > len(ending):
                cleaned = cleaned[: -len(ending)]
                break
        else:
            break
    return cleaned


def _similar(a: str, b: str, threshold: float) -> bool:
    """두 문장이 threshold 이상 닮았는지. 값싼 검사부터 해서 대부분을 걸러낸다."""
    # 길이 차이만으로 threshold 를 못 넘는다면 더 볼 것도 없다.
    short, long = sorted((len(a), len(b)))
    if long == 0 or short / long < threshold:
        return False

    matcher = SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
        return False
    return matcher.ratio() >= threshold


def group_questions(
    items: list[dict[str, Any]], threshold: float = 0.8, limit: int = 10
) -> list[dict[str, Any]]:
    """질문 목록을 비슷한 것끼리 묶어 많이 물은 순으로 돌려준다.

    items 의 각 원소는 text / model / agents / elapsed_ms / created_at 를 갖는다.

    같은 문장이 대부분이므로 **먼저 다듬은 결과가 똑같은 것끼리 모으고**, 그렇게 줄어든
    서로 다른 문장들만 유사도로 비교한다. 처음부터 전부 비교하면 질문이 늘수록
    급격히 느려진다.
    """
    exact: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = normalize(item.get("text", ""))
        if key:
            exact.setdefault(key, []).append(item)

    # 많이 나온 문장이 묶음의 대표가 되도록 큰 것부터 본다.
    keys = sorted(exact, key=lambda k: len(exact[k]), reverse=True)

    clusters: list[dict[str, Any]] = []
    for key in keys:
        for cluster in clusters:
            if _similar(key, cluster["key"], threshold):
                cluster["members"].extend(exact[key])
                break
        else:
            clusters.append({"key": key, "members": list(exact[key])})

    clusters.sort(key=lambda c: len(c["members"]), reverse=True)
    return [_summarize(c) for c in clusters[:limit]]


def _summarize(cluster: dict[str, Any]) -> dict[str, Any]:
    """묶음 하나를 화면에 쓸 형태로 정리한다."""
    members = cluster["members"]

    # 모델별 평균 소요 시간. 같은 질문을 다른 모델로 던진 결과가 나란히 보이면
    # 모델 사이의 속도 차이를 바로 비교할 수 있다.
    by_model: dict[str, list[int]] = {}
    agents: dict[str, int] = {}
    wording: dict[str, int] = {}  # 실제로 쓰인 표현들
    for m in members:
        text = (m.get("text") or "").strip()
        if text:
            wording[text] = wording.get(text, 0) + 1

        model = m.get("model")
        elapsed = m.get("elapsed_ms") or 0
        if model and elapsed:
            by_model.setdefault(model, []).append(elapsed)

        for agent_id in m.get("agents") or []:
            if agent_id:
                agents[agent_id] = agents.get(agent_id, 0) + 1

    models = [
        {"model": name, "count": len(values), "avg_ms": round(sum(values) / len(values))}
        for name, values in sorted(by_model.items(), key=lambda kv: -len(kv[1]))
    ]
    # 가장 많이 쓰인 표현을 대표로 삼는다.
    label = max(wording.items(), key=lambda kv: kv[1])[0] if wording else ""

    times = [m["created_at"] for m in members if m.get("created_at")]
    return {
        "question": label,
        "count": len(members),
        "variants": len(wording),
        "agents": [a for a, _ in sorted(agents.items(), key=lambda kv: -kv[1])],
        "models": models,
        "last_at": max(times).isoformat() if times else None,
    }
