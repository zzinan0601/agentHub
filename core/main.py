"""코어(코디네이터) 서버 진입점.

  python -m core.main       또는       run_core.bat
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from core import migrate, scheduler
from core.config import settings
from core.contract import CONTRACT_VERSION
from core.db import init_db
from core.registry import registry
from core.routers import agents, auth, chat, insights, rooms, schedules, workflows

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("core")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await migrate.run()  # 기존 테이블에 나중에 추가된 컬럼을 채운다
    await registry.refresh()  # 첫 목록은 즉시 채우고,
    registry.start()  # 이후에는 주기적으로 갱신한다
    scheduler.install_listeners()
    scheduler.scheduler.start()
    await scheduler.load_all()
    log.info("코어 기동 완료 (계약 v%s, 기본 모델 %s)", CONTRACT_VERSION, settings.default_model)
    yield
    scheduler.scheduler.shutdown(wait=False)
    await registry.stop()


app = FastAPI(title="에이전트 허브", version=CONTRACT_VERSION, lifespan=lifespan)

# 개발 중에는 Vue 개발 서버(5173)가 다른 포트에서 뜬다.
# 쿠키를 주고받으므로 allow_origins 에 "*" 를 쓸 수 없다(브라우저가 거부한다).
# 폐쇄망에서는 코어가 dist 를 직접 서빙해 같은 출처라 CORS 자체가 필요 없고,
# 개발 중 Vue 개발 서버(5173)만 예외로 열어준다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(chat.router)
app.include_router(agents.router)
app.include_router(schedules.router)
app.include_router(schedules.cron_router)
app.include_router(insights.router)
app.include_router(workflows.router)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "agents": len(registry.all()),
        "online": len(registry.online()),
    }


# 빌드된 UI 가 있으면 코어가 직접 서빙한다. (폐쇄망에서는 이 방식만 쓴다)
_dist = Path(settings.ui_dist_dir)
if _dist.is_dir():

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """화면 라우팅은 브라우저가 한다. 서버는 실제 파일이면 그것을, 아니면 index.html 을 준다.

        /insights 같은 주소를 새로고침하거나 북마크로 열면 서버에 그 경로가 오는데,
        디스크에 그런 파일은 없다. 이 폴백이 없으면 404 가 난다.
        단, /api 로 시작하는 주소는 폴백하지 않는다. 폴백하면 없는 API 를 불러도
        200 + index.html 이 돌아가 호출한 쪽이 오류를 알아채지 못한다.
        """
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail="not found")
        candidate = _dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")

else:
    log.info("UI 빌드 결과가 없습니다(%s). 개발 중에는 npm run dev 를 쓰세요.", _dist)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.core_host, port=settings.core_port)
