"""워크플로우 편집 API 검사.

화면에서 워크플로우를 만들고 고치고 지울 수 있게 되면서 코어가 **파일을 쓴다.**
경로가 새거나, 못 쓸 yaml 이 저장되거나, 쓰고 있는 워크플로우가 지워지면 안 된다.
그 세 가지를 실제 서버에 대고 확인한다.

    python scripts/test_workflow_api.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402

BASE = os.environ.get("CORE_URL", "http://localhost:8000")
WF_DIR = Path(settings.workflows_dir).resolve()
TEST_KEY = "zz-test-workflow"

ok_count = 0
fail_count = 0


def check(label: str, passed: bool, detail: str = "") -> None:
    global ok_count, fail_count
    if passed:
        ok_count += 1
        print(f"  [OK] {label}")
    else:
        fail_count += 1
        print(f"  [XX] {label}  {detail}")


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=20.0)

    # 로그인 없이 쓰기를 시도하면 막혀야 한다.
    anon = httpx.Client(base_url=BASE, timeout=10.0)
    r = anon.put(f"/api/workflows/{TEST_KEY}", json={"source": "name: x"})
    check("로그인 없이 저장 거부", r.status_code == 401, f"-> {r.status_code}")
    r = anon.delete(f"/api/workflows/{TEST_KEY}")
    check("로그인 없이 삭제 거부", r.status_code == 401, f"-> {r.status_code}")
    anon.close()

    c.post("/api/auth/login", json={"username": "워크플로우점검"}).raise_for_status()

    # --- 원문 조회 ------------------------------------------------------------
    listed = c.get("/api/workflows").json()
    check("목록에 editable 이 실린다", listed.get("editable") is True)
    first = listed["workflows"][0]["key"]
    src = c.get(f"/api/workflows/{first}/source").json()
    on_disk = (WF_DIR / f"{first}.yaml").read_text(encoding="utf-8")
    check("원문이 파일과 글자 하나까지 같다", src["source"] == on_disk)

    # --- 검증 ----------------------------------------------------------------
    def validate(text: str) -> dict:
        return c.post("/api/workflows/validate", json={"source": text}).json()

    v = validate("name: [깨진\n  yaml:")
    check("문법 오류를 잡는다", not v["valid"] and "줄" in v["errors"][0], str(v["errors"]))
    v = validate("name: 빈것\nsteps: []")
    check("빈 steps 를 잡는다", not v["valid"])
    v = validate("name: 없는것\nsteps:\n  - agent: 없는에이전트")
    check("등록되지 않은 에이전트를 잡는다", not v["valid"], str(v["errors"]))
    v = validate("name: 모드\nmode: 아무거나\nsteps:\n  - agent: echo")
    check("mode 값을 잡는다", not v["valid"], str(v["errors"]))
    v = validate("name: 정상\ndescription: 설명\nmode: sequential\nsteps:\n  - agent: echo")
    check("정상이면 통과한다", v["valid"] and not v["warnings"], str(v))
    check("미리보기에 이름과 순서가 실린다",
          v["preview"]["steps"] and v["preview"]["steps"][0]["agent"] == "echo")

    # --- 이름 규칙 -------------------------------------------------------------
    body = {"source": "name: 나쁨\nsteps:\n  - agent: echo", "base_mtime": None}
    # ../escape 는 주소가 /api/escape 로 정규화돼 라우트에 아예 닿지 않는다(405).
    # 정규화를 피해 핸들러까지 들어오는 경우까지 보려고 인코딩한 것도 함께 던진다.
    for bad in ("../escape", "%2E%2E%2Fescape", "UPPER", "공백 이름"):
        r = c.put(f"/api/workflows/{bad}", json=body)
        check(f"이상한 이름 거부: {bad}", r.status_code in (400, 404, 405), f"-> {r.status_code}")
    check("폴더 밖에 파일이 생기지 않았다", not (WF_DIR.parent / "escape.yaml").exists())

    # --- 신규 생성 -------------------------------------------------------------
    path = WF_DIR / f"{TEST_KEY}.yaml"
    if path.exists():
        path.unlink()
    source = (
        "# 검사용으로 만든 워크플로우입니다.\n"
        "name: 점검용\ndescription: 자동 검사가 만든 것\nmode: sequential\n"
        "steps:\n  - agent: echo\n  - agent: summary\n"
    )
    r = c.put(f"/api/workflows/{TEST_KEY}", json={"source": source, "base_mtime": None})
    check("신규 생성", r.status_code == 200, r.text[:120])
    saved = r.json()
    check("파일이 실제로 생겼다", path.exists())
    check("맨 윗줄에 수정자가 남는다", saved["source"].startswith("# 마지막 수정: 워크플로우점검"))
    check("본문 주석이 살아 있다", "검사용으로 만든" in saved["source"])

    names = [w["key"] for w in c.get("/api/workflows").json()["workflows"]]
    check("목록에 곧바로 나타난다 (재기동 없이)", TEST_KEY in names)

    r = c.put(f"/api/workflows/{TEST_KEY}", json={"source": source, "base_mtime": None})
    check("같은 이름으로 또 만들면 거부", r.status_code == 409, f"-> {r.status_code}")

    # --- 수정 ------------------------------------------------------------------
    r = c.put(
        f"/api/workflows/{TEST_KEY}",
        json={"source": saved["source"].replace("점검용", "점검용2"), "base_mtime": saved["mtime"]},
    )
    check("수정", r.status_code == 200, r.text[:120])
    second = r.json()
    stamps = [ln for ln in second["source"].splitlines() if ln.startswith("# 마지막 수정:")]
    check("수정 이력 줄은 늘 하나뿐이다", len(stamps) == 1, str(stamps))

    r = c.put(
        f"/api/workflows/{TEST_KEY}", json={"source": source, "base_mtime": saved["mtime"]}
    )
    check("옛 mtime 으로 저장하면 거부 (동시 편집)", r.status_code == 409, f"-> {r.status_code}")

    r = c.put(
        f"/api/workflows/{TEST_KEY}",
        json={"source": "name: 나쁨\nsteps: []", "base_mtime": second["mtime"]},
    )
    check("검증에 걸리면 저장하지 않는다", r.status_code == 400, f"-> {r.status_code}")
    check("거부된 내용이 파일에 반영되지 않았다", "점검용2" in path.read_text(encoding="utf-8"))

    # --- 실제로 도는지 ----------------------------------------------------------
    room = c.post("/api/rooms", json={"title": "워크플로우 점검방"}).json()
    c.patch(f"/api/rooms/{room['id']}", json={"workflow": TEST_KEY})
    check("방에 새 워크플로우를 걸 수 있다",
          c.get(f"/api/rooms/{room['id']}").json()["workflow"] == TEST_KEY)

    # --- 삭제 ------------------------------------------------------------------
    r = c.delete(f"/api/workflows/{TEST_KEY}")
    check("쓰는 방이 있으면 삭제 거부", r.status_code == 409, f"-> {r.status_code}")
    check("거부 문구에 방 이름이 있다", "워크플로우 점검방" in r.text, r.text[:150])
    check("거부됐으니 파일은 남아 있다", path.exists())

    c.patch(f"/api/rooms/{room['id']}", json={"workflow": ""})
    r = c.delete(f"/api/workflows/{TEST_KEY}")
    check("해제 후 삭제", r.status_code == 200, r.text[:120])
    check("파일이 사라졌다", not path.exists())

    r = c.get(f"/api/workflows/{TEST_KEY}/source")
    check("없는 워크플로우 조회는 404", r.status_code == 404, f"-> {r.status_code}")

    c.delete(f"/api/rooms/{room['id']}")
    c.close()

    print(f"\n  {ok_count + fail_count}개 중 {ok_count}개 통과")
    return 1 if fail_count else 0


if __name__ == "__main__":
    print("\n워크플로우 편집 API 검사\n")
    sys.exit(main())
