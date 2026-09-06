"""라우터 로그를 요약해서 보여준다.

폐쇄망에서 "자동 선택이 계속 실패한다" 를 알아보려면 **무엇이 나왔길래 실패했는지**가
있어야 한다. 코어가 `logs/router.log` 에 응답 원문을 통째로 남기고, 이 명령이 그것을
사람이 읽을 수 있게 간추린다.

    python scripts/router_log.py            # 요약 + 마지막 실패 3건
    python scripts/router_log.py -n 10      # 마지막 실패 10건
    python scripts/router_log.py --all      # 파일 전체를 그대로
    python scripts/router_log.py --clear    # 지우고 새로 시작

이 출력을 그대로 복사해서 전달하면 원인을 짚을 수 있다.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402

SEP = "=" * 78


def main() -> int:
    args = sys.argv[1:]
    path = Path(settings.router_log_path or "./logs/router.log")

    if not path.is_file():
        print(f"\n로그가 없습니다: {path}")
        print("아직 라우팅이 한 번도 돌지 않았거나 ROUTER_LOG_PATH 가 비어 있습니다.")
        print("에이전트를 고르지 않고 질문을 한 번 던져보세요.")
        return 1

    if "--clear" in args:
        path.unlink()
        print(f"지웠습니다: {path}")
        return 0

    text = path.read_text(encoding="utf-8", errors="replace")

    if "--all" in args:
        print(text)
        return 0

    lines = text.split("\n")
    ok_lines = [ln for ln in lines if " OK    model=" in ln]
    # 실패는 구분선으로 나뉜 덩어리다.
    blocks = [b for b in text.split(SEP) if "라우터 JSON 파싱 실패" in b]
    gave_up = text.count("*** 끝내 실패")

    print(f"\n{SEP}")
    print(f"라우터 로그 요약  ({path}, {path.stat().st_size / 1024:.0f}KB)")
    print(SEP)
    total = len(ok_lines) + len(blocks)
    print(f"  성공 {len(ok_lines)}건 / 실패 {len(blocks)}건" + (f" / 총 {total}회 호출" if total else ""))
    if gave_up:
        print(f"  이 중 {gave_up}건은 재시도까지 다 실패해 에이전트 없이 답했습니다.")

    if blocks:
        print("\n  실패 원인별:")
        reasons = Counter()
        models = Counter()
        for b in blocks:
            for ln in b.split("\n"):
                if ln.startswith("진단"):
                    reasons[ln.split(":", 1)[1].strip()] += 1
                elif ln.startswith("model "):
                    models[ln.split(":", 1)[1].strip()] += 1
        for reason, n in reasons.most_common():
            print(f"    {n:>3}건  {reason}")
        if len(models) > 1:
            print("\n  모델별 실패:")
            for m, n in models.most_common():
                print(f"    {n:>3}건  {m}")

        n = 3
        if "-n" in args:
            try:
                n = int(args[args.index("-n") + 1])
            except (IndexError, ValueError):
                pass
        print(f"\n{SEP}\n마지막 실패 {min(n, len(blocks))}건 (원문 그대로)\n{SEP}")
        for b in blocks[-n:]:
            print(b.strip())
            print(SEP)
    else:
        print("\n  실패한 적이 없습니다.")

    if ok_lines:
        print("\n  최근 성공 3건:")
        for ln in ok_lines[-3:]:
            print(f"    {ln}")

    print(f"\n  전체를 보려면: python scripts/router_log.py --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
