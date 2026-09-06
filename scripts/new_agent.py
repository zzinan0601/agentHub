"""내 에이전트 폴더를 만든다. (개발자가 처음 한 번 실행)

    python scripts/new_agent.py sales-report "홍길동"
    python scripts/new_agent.py sales-report "홍길동" 9020   # 포트를 바꾸고 싶을 때만

agent_template 을 agents/<id>/ 로 복사하고 manifest.yaml 과 .env 의 값을 채워준다.

에이전트는 각자 자기 노트북에서 돌고 노트북마다 IP 가 다르므로 포트를 나눠 가질
필요가 없다. 전원이 같은 값(DEFAULT_PORT)을 쓴다. 한 대에서 두 개를 띄울 때만 바꾼다.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 모두가 쓰는 기본 포트. 9001/9002 는 예제 에이전트가 쓰므로 피한다.
DEFAULT_PORT = "9010"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    agent_id = sys.argv[1]
    owner = sys.argv[2] if len(sys.argv) > 2 else "미지정"
    port = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PORT

    dst = ROOT / "agents" / agent_id
    if dst.exists():
        print(f"이미 있습니다: {dst}")
        return 1

    # __pycache__ 나 이전에 만들어둔 .env, files 는 복사하지 않는다.
    shutil.copytree(
        ROOT / "agent_template",
        dst,
        ignore=shutil.ignore_patterns("__pycache__", ".venv", ".env", "files"),
    )

    manifest = dst / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace("id: my-agent", f"id: {agent_id}")
    text = text.replace("owner: 홍길동", f"owner: {owner}")
    manifest.write_text(text, encoding="utf-8")

    env = dst / ".env"
    env_text = (dst / ".env.example").read_text(encoding="utf-8")
    env.write_text(env_text.replace(f"AGENT_PORT={DEFAULT_PORT}", f"AGENT_PORT={port}"), encoding="utf-8")

    print(f"만들었습니다: agents/{agent_id}")
    print("다음 순서로 진행하세요.")
    print(f"  1) cd agents/{agent_id} && setup.bat")
    print("  2) manifest.yaml 의 name/description/examples 를 채운다")
    print("  3) agent.py 의 fetch_business_data() 에 업무 로직을 넣는다")
    print("  4) run.bat 으로 띄우고 python scripts/check_contract.py 로 자가검사")
    print(f"  5) registry.yaml 에 {agent_id} 를 추가한다 (url: http://<내 노트북 IP>:{port})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
