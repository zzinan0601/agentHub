"""계약 고정부를 각 에이전트 폴더까지 맞춘다.

폐쇄망이라 공용 라이브러리를 사내 인덱스에 올릴 수 없어 복사본으로 관리한다.
그래서 원본을 고치면 복사본들이 조용히 뒤처진다.

두 단계로 맞춘다.

1. `core/contract.py`, `core/llm.py`  ->  `agent_template/`
2. `agent_template/` 의 고정부 4개    ->  `agents/*/`

    python scripts/sync_contract.py            # 무엇이 다른지 보여주고 맞춘다
    python scripts/sync_contract.py --check    # 고치지 않고 다른 것만 알려준다 (CI 용)

**`main.py` 와 `files.py` 도 고정부다.** 예전에는 contract.py / llm.py 만 맞췄는데,
그러면 main.py 를 고쳐도 이미 만들어진 에이전트에는 영영 반영되지 않는다.
고정부는 개발자가 손대지 않기로 한 파일이므로 덮어써도 안전하다.
개발자가 만지는 파일(agent.py, manifest.yaml, prompt.md, .env, requirements.txt)은
건드리지 않는다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# core 와 템플릿이 함께 쓰는 파일
CORE_SHARED = ["contract.py", "llm.py"]
# 에이전트가 손대지 않기로 한 계약 고정부 (DEVELOPER_GUIDE 의 '수정 금지' 목록과 같다)
AGENT_FIXED = ["main.py", "contract.py", "llm.py", "files.py"]


def sync(src: Path, dst: Path, check: bool, label: str) -> bool:
    """다르면 복사한다(check 면 알리기만). 실제로 달랐는지 돌려준다."""
    if not src.is_file():
        return False
    if dst.is_file() and src.read_bytes() == dst.read_bytes():
        return False
    if check:
        print(f"  [다름] {label}")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"  [갱신] {label}")
    return True


def main() -> int:
    check = "--check" in sys.argv
    stale = 0

    print("\n1) core -> agent_template")
    for name in CORE_SHARED:
        stale += sync(ROOT / "core" / name, ROOT / "agent_template" / name, check, name)

    print("\n2) agent_template -> agents/*")
    agents_dir = ROOT / "agents"
    if agents_dir.is_dir():
        for folder in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
            for name in AGENT_FIXED:
                stale += sync(
                    ROOT / "agent_template" / name,
                    folder / name,
                    check,
                    f"{folder.name}/{name}",
                )

    if not stale:
        print("\n전부 같습니다.")
        return 0

    if check:
        print(f"\n{stale}개가 원본과 다릅니다. 인자 없이 다시 실행하면 맞춥니다.")
        return 1

    print(f"\n{stale}개를 맞췄습니다.")
    print("다른 노트북에서 도는 에이전트는 여기서 맞출 수 없습니다.")
    print("agent_template 을 다시 배포하거나, 담당자에게 위 4개 파일을 덮어쓰라고 공지하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
