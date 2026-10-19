import logging

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import admin, auth, misc, requests
from app.db import get_db
from app.services import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Заявки образовательных учреждений",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

api = APIRouter(prefix="/api")
for module in (auth, requests, misc, admin):
    api.include_router(module.router)


@api.get("/health", tags=["service"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "llm_configured": llm.is_configured()}


app.include_router(api)
