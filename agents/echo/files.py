"""첨부파일(이미지/엑셀/PDF) 저장 - 계약 고정부. 수정하지 않는다.

파일 실물은 이 에이전트를 띄운 노트북의 디스크에 남고, 코어는 GET /files/{name} 으로
받아가 브라우저에 중계한다. 오래된 파일은 TTL 이 지나면 기동 시 자동으로 지운다.

agent.py 에서 이렇게 쓴다:

    from files import save_bytes
    att = save_bytes(png_bytes, "매출차트.png")
    yield result("![차트](attachment:%s)" % att.file, attachments=[att])
"""

from __future__ import annotations

import mimetypes
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from contract import Attachment, is_safe_file_name

load_dotenv()

FILES_DIR = Path(os.getenv("AGENT_FILES_DIR", "./files")).resolve()
FILE_TTL_HOURS = int(os.getenv("AGENT_FILE_TTL_HOURS", 72))


def _ensure_dir() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def save_bytes(data: bytes, name: str, mime: str | None = None) -> Attachment:
    """바이트를 파일로 저장하고 Attachment 를 돌려준다.

    같은 이름이 겹쳐도 덮어쓰지 않도록 uuid 를 앞에 붙인 저장용 이름을 따로 만든다.
    화면에 보이는 이름(name)은 사용자가 지정한 그대로 유지된다.
    """
    _ensure_dir()
    suffix = Path(name).suffix
    stored = f"{uuid.uuid4().hex}{suffix}"
    path = FILES_DIR / stored
    path.write_bytes(data)

    if mime is None:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    # 내려줄 때 mime 을 다시 추측하지 않도록 옆에 적어둔다.
    # (윈도우는 .csv 를 application/vnd.ms-excel 로 추측해 charset 이 사라진다)
    path.with_suffix(path.suffix + ".mime").write_text(mime, encoding="utf-8")
    return Attachment(name=name, file=stored, mime=mime, size=len(data))


# 엑셀이 열 확률이 높은 확장자. 여기에는 BOM 을 붙인다.
_BOM_SUFFIXES = (".csv", ".tsv")
_UTF8_BOM = "﻿"


def save_text(
    text: str, name: str, mime: str = "text/plain; charset=utf-8", bom: bool | None = None
) -> Attachment:
    """텍스트(CSV, 로그 등)를 UTF-8 파일로 저장한다.

    bom: UTF-8 BOM 을 앞에 붙일지. 기본은 .csv / .tsv 일 때만 붙인다.

    엑셀은 내려받은 csv 를 열 때 HTTP 의 charset 을 보지 않고 파일 바이트만 본다.
    BOM 이 없으면 한국어 윈도우에서 시스템 코드페이지(CP949)로 가정해 한글이 깨진다.
    BOM 이 있으면 UTF-8 로 인식한다. 다른 텍스트 파일에는 BOM 이 오히려 방해가 될 수
    있어 붙이지 않는다.
    """
    if bom is None:
        bom = name.lower().endswith(_BOM_SUFFIXES)
    if bom and not text.startswith(_UTF8_BOM):
        text = _UTF8_BOM + text
    return save_bytes(text.encode("utf-8"), name, mime)


def resolve(file_name: str) -> Path | None:
    """저장된 파일 경로를 찾는다. 이름이 안전하지 않거나 없으면 None."""
    if not is_safe_file_name(file_name) or file_name.endswith(".mime"):
        return None
    path = FILES_DIR / file_name
    return path if path.is_file() else None


def mime_of(path: Path) -> str:
    """저장할 때 적어둔 mime 을 읽는다. 없으면 확장자로 추측한다."""
    sidecar = path.with_suffix(path.suffix + ".mime")
    if sidecar.is_file():
        return sidecar.read_text(encoding="utf-8").strip()
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def cleanup_expired() -> int:
    """TTL 이 지난 파일을 지우고 지운 개수를 돌려준다. 기동 시 한 번 호출된다."""
    if not FILES_DIR.is_dir():
        return 0
    deadline = time.time() - FILE_TTL_HOURS * 3600
    removed = 0
    for path in FILES_DIR.iterdir():
        if path.is_file() and path.stat().st_mtime < deadline:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
