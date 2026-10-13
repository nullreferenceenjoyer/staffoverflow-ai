import logging

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    analytics,
    auth,
    knowledge,
    misc,
    norms,
    organizations,
    program,
    projects,
    requests,
    workflow,
)
from app.db import get_db
from app.deps import require_analytics_access
from app.services import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Оптимизация кадрового потенциала ОУ",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

api = APIRouter(prefix="/api")
for module in (auth, requests, misc):
    api.include_router(module.router)
# Всё, что касается штатных расписаний, закрыто для ролей, работающих только с заявками
for module in (organizations, analytics, norms, projects, program, workflow, knowledge):
    api.include_router(module.router, dependencies=[Depends(require_analytics_access)])


@api.get("/health", tags=["service"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "llm_configured": llm.is_configured()}


app.include_router(api)
