"""Общие фикстуры.

Юнит-тесты базы не требуют. Тесты API (test_api.py) запускаются только при заданной
TEST_DATABASE_URL — им нужен PostgreSQL с расширением pgvector:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
    TEST_DATABASE_URL=postgresql+psycopg://hr:<пароль>@127.0.0.1:54320/hr_edu_test pytest
"""

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# Тесты всегда идут на профиле из репозитория, даже если рядом лежит seed/local.json
DEMO_PROFILE = Path(__file__).resolve().parents[2] / "seed" / "demo.json"
if TEST_DATABASE_URL:
    # Должно быть выставлено до первого импорта app.db: движок создаётся при импорте
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("STORAGE_DIR", os.path.join(os.path.dirname(__file__), ".storage"))


def _create_database(url: str) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def client():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL не задан")
    _create_database(TEST_DATABASE_URL)

    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed.ensure_reference_data(db)
        seed.seed_demo(db, org_count=8, profile=seed.load_profile(DEMO_PROFILE))

    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session")
def login(client):
    """Возвращает функцию: e-mail демо-пользователя -> заголовки авторизации."""
    cache: dict[str, dict] = {}

    def _login(email: str, password: str = "demo12345") -> dict:
        if email not in cache:
            response = client.post("/api/auth/login", data={"username": email,
                                                            "password": password})
            assert response.status_code == 200, response.text
            cache[email] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return cache[email]

    return _login
