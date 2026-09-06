"""첨부파일 인코딩 확인 - 엑셀에서 한글이 깨지지 않는지 검사한다.

엑셀은 내려받은 .csv 를 열 때 HTTP 의 charset 을 보지 않고 파일 바이트만 본다.
UTF-8 BOM 이 없으면 한국어 윈도우에서 시스템 코드페이지(CP949)로 가정해 한글이 깨진다.
그래서 save_text() 는 csv/tsv 에 BOM 을 붙인다.

    python scripts/test_attachment_encoding.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent_template"))

# files.py 는 AGENT_FILES_DIR 을 import 시점에 읽으므로 먼저 임시 폴더로 돌려둔다.
import os  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="attach-test-")
os.environ["AGENT_FILES_DIR"] = _tmp

import files  # noqa: E402

BOM = b"\xef\xbb\xbf"
passed = failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [OK  ] {name}" + (f"  -> {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {name}" + (f"  -> {detail}" if detail else ""))


def main() -> int:
    csv_text = "지점,매출\n서울점,1240000\n"

    print("\n[1] CSV - 엑셀이 UTF-8 로 인식해야 한다")
    att = files.save_text(csv_text, "매출.csv", mime="text/csv; charset=utf-8")
    raw = (Path(_tmp) / att.file).read_bytes()
    check("BOM 으로 시작", raw.startswith(BOM), raw[:6].hex())
    check("BOM 뒤는 UTF-8 한글", raw[3:].decode("utf-8").startswith("지점,매출"))
    check("size 가 실제 바이트 수와 일치", att.size == len(raw), f"{att.size} / {len(raw)}")
    check("mime 유지", att.mime == "text/csv; charset=utf-8", att.mime)

    print("\n[2] 일반 텍스트 - BOM 을 붙이지 않는다")
    att2 = files.save_text("안녕하세요\n", "메모.txt")
    raw2 = (Path(_tmp) / att2.file).read_bytes()
    check("BOM 없음", not raw2.startswith(BOM), raw2[:6].hex())
    check("UTF-8 로 읽힘", raw2.decode("utf-8").startswith("안녕하세요"))

    print("\n[3] 바이너리 - 손대지 않는다")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    att3 = files.save_bytes(png, "그림.png")
    raw3 = (Path(_tmp) / att3.file).read_bytes()
    check("바이트가 그대로", raw3 == png)
    check("mime 추정", att3.mime == "image/png", att3.mime)

    print("\n[4] BOM 을 끄고 싶을 때")
    att4 = files.save_text(csv_text, "원본.csv", mime="text/csv", bom=False)
    raw4 = (Path(_tmp) / att4.file).read_bytes()
    check("bom=False 면 붙지 않음", not raw4.startswith(BOM), raw4[:6].hex())

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
