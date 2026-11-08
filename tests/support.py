"""Helpers shared by the tests: settings, accounts and the test database.

The tests use a fresh SQLite file each. With TEST_DATABASE_URL set (CI's Postgres
job), the API and storage tests use that Postgres database instead, emptied before
each test. Its name must contain "test", because every table in it is dropped.
"""

import os
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip() or None
PASSWORD = "correct horse battery staple"
EMAIL = "person@example.com"


def on_postgres() -> bool:
    return TEST_DATABASE_URL is not None


def reset_postgres(url: str) -> None:
    database = make_url(url).database or ""
    if "test" not in database:
        raise RuntimeError(
            f"TEST_DATABASE_URL names the database {database!r}. Use one with 'test' in "
            "its name: the tests drop every table in it."
        )
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            # A connection an earlier test left open would make the drop wait forever.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def make_settings(database_url: str, **values: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": database_url,
        "max_upload_mb": 1,
        "retention_hours": 24,
        "log_level": "WARNING",
        # Tests never load real models. Matching by meaning is tested with fakes.
        "semantic_matching": "off",
        # Tests never call Claude. The LLM features are tested with a fake client.
        "llm_enabled": "off",
    }
    return Settings(_env_file=None, **(base | values))  # type: ignore[call-arg]


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> None:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 202, response.text


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["token"]
    return token


def authenticate(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    """Register, log in and send the token with every later request of `client`."""
    register(client, email, password)
    token = login(client, email, password)
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
