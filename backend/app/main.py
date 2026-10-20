import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import admin, assistant, auth, live, misc, norms, requests, staffing
from app.config import get_settings
from app.db import get_db
from app.services import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def watch_llm() -> None:
    """Проверяет модель по расписанию, чтобы о сбое узнать до того, как придёт заявка."""
    while True:
        try:
            await asyncio.to_thread(llm.check)
        except Exception:
            log.exception("LLM check failed")
        await asyncio.sleep(max(get_settings().llm_check_interval_s, 10))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Сменилась доступность модели — открытые страницы узнают об этом сразу
    llm.on_change(lambda _state: live.hub.broadcast_threadsafe({"type": "llm"}))
    tasks = [asyncio.create_task(live.hub.run()), asyncio.create_task(watch_llm())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Заявки образовательных учреждений",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

api = APIRouter(prefix="/api")
for module in (auth, requests, misc, admin, live, staffing, norms, assistant):
    api.include_router(module.router)


@api.get("/health", tags=["service"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    state = llm.status()
    return {"status": "ok", "llm_configured": state["configured"],
            "llm_available": state["available"], "live": live.hub.connected}


app.include_router(api)
