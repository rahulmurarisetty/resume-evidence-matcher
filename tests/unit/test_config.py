"""Settings, and what APP_ENV=production refuses."""

import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app import main
from app.config import Settings
from app.errors import StartupError
from app.main import create_app
from tests.support import make_settings

GOOD_PG = "postgresql+psycopg://app:s3cret@db.example.com:5432/app?sslmode=require"


def _production(**values: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "production",
        "scanner": "clamav",
        "cors_origins": "https://ui.example.com",
    }
    database_url = values.pop("database_url", GOOD_PG)
    return make_settings(database_url, **(base | values))


def test_a_good_production_setup_has_no_problems() -> None:
    settings = _production()
    assert settings.production_problems() == []
    assert settings.startup_warnings() == []
    assert settings.is_production and not settings.auto_migrate


@pytest.mark.parametrize(
    ("values", "problem"),
    [
        ({"database_url": "sqlite:///./data/app.db"}, "SQLite"),
        ({"database_url": "postgresql+psycopg://app@db/app?sslmode=require"}, "no password"),
        ({"database_url": "postgresql+psycopg://app:pw@db/app"}, "sslmode=require"),
        ({"database_url": "postgresql+psycopg://app:pw@db/app?sslmode=prefer"}, "sslmode"),
        ({"database_url": "not a url"}, "not a database URL"),
        ({"auth_mode": "disabled"}, "AUTH_MODE=disabled"),
        ({"scanner": "off"}, "SCANNER=off"),
        ({"cors_origins": "*"}, "CORS_ORIGINS=*"),
        ({"llm_enabled": "on"}, "ANTHROPIC_API_KEY"),
    ],
)
def test_production_problems(values: dict[str, Any], problem: str) -> None:
    problems = _production(**values).production_problems()
    assert len(problems) == 1 and problem in problems[0]


def test_verify_full_is_accepted() -> None:
    url = GOOD_PG.replace("require", "verify-full")
    assert _production(database_url=url).production_problems() == []


def test_local_mode_has_no_production_rules() -> None:
    assert make_settings("sqlite://", auth_mode="disabled").production_problems() == []


def test_unscanned_uploads_are_allowed_only_with_a_warning() -> None:
    settings = _production(scanner="off", allow_unscanned_uploads=True)
    assert settings.production_problems() == []
    [warning] = settings.startup_warnings()
    assert "UPLOADS ARE NOT SCANNED" in warning
    assert "RATE LIMITS ARE OFF" in _production(rate_limits_enabled=False).startup_warnings()[0]


def test_create_app_refuses_unsafe_production_settings() -> None:
    settings = _production(database_url="sqlite:///x.db", auth_mode="disabled")
    with pytest.raises(StartupError, match="refuses to start") as error:
        create_app(settings)
    assert "SQLite" in str(error.value) and "AUTH_MODE" in str(error.value)


def test_create_app_logs_the_warnings(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep pytest's log handler: configure_logging would replace it.
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    settings = _production(scanner="off", allow_unscanned_uploads=True)
    with caplog.at_level(logging.WARNING):
        create_app(settings)  # doesn't connect: the database is used only at startup
    assert any("UPLOADS ARE NOT SCANNED" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///./data/app.db", "sqlite:///./data/app.db"),
    ],
)
def test_postgres_urls_get_the_driver(given: str, stored: str) -> None:
    assert make_settings(given).database_url == stored


def test_values_are_read_case_insensitively() -> None:
    settings = make_settings(
        "sqlite://", app_env=" Production ", auth_mode="DISABLED", scanner="ClamAV"
    )
    assert (settings.app_env, settings.auth_mode, settings.scanner) == (
        "production",
        "disabled",
        "clamav",
    )


@pytest.mark.parametrize(
    "values",
    [
        {"app_env": "prod"},
        {"auth_mode": "optional"},
        {"scanner": "defender"},
        {"rate_limit_auth": "lots"},
        {"trusted_proxies": "everyone"},
        {"session_ttl_hours": 0},
    ],
)
def test_bad_values_are_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings("sqlite://", **values)


def test_blank_db_auto_migrate_means_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_AUTO_MIGRATE", "")
    assert Settings(_env_file=None).db_auto_migrate is None  # type: ignore[call-arg]
    monkeypatch.setenv("DB_AUTO_MIGRATE", "false")
    assert Settings(_env_file=None).auto_migrate is False  # type: ignore[call-arg]


def test_rates_and_proxies() -> None:
    settings = make_settings("sqlite://", rate_limit_exports="7/day", trusted_proxies="10.0.0.0/8")
    assert settings.rates["exports"].count == 7
    assert set(settings.rates) == {"auth", "analyses", "suggestions", "exports"}
    assert settings.proxies.trusts("10.9.9.9") and not settings.proxies.trusts("8.8.8.8")


def test_every_setting_is_documented() -> None:
    root = Path(__file__).resolve().parents[2]
    example = (root / ".env.example").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    table = readme[readme.index("## Configuration") : readme.index("## Security and privacy")]
    for name in Settings.model_fields:
        assert f"\n{name.upper()}=" in example, f"{name.upper()} is missing from .env.example"
        assert f"| `{name.upper()}` |" in table, f"{name.upper()} is missing from the README table"
