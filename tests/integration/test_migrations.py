"""The Alembic migrations: they build exactly the schema the models describe, the
app runs them or refuses to start without them, and a database file from v0.5 or
earlier still starts, with its analyses kept for the local account.

The v0.2 and v0.5 tests replace v0.5's test_storage_upgrade.py, which checked that
a v0.2 file still started after v0.3 added tables."""

import io
import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text

from app.errors import StartupError
from app.main import create_app
from app.services.analysis import analyze
from app.storage import migrations
from app.storage.accounts import LOCAL_USER_ID
from app.storage.db import Base, make_engine
from app.storage.migrations import (
    alembic_config,
    ensure_current,
    head_revision,
    schema_status,
    upgrade,
)
from tests.builders import build_pdf
from tests.support import authenticate, make_settings, on_postgres

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "users",
    "sessions",
    "analyses",
    "analysis_resumes",
    "suggestions",
    "suggestion_runs",
    "span_corrections",
    "gap_answers",
    "alembic_version",
}
PDF = "application/pdf"

# The analyses table as v0.2's create_all made it on SQLite (v0.5's test file kept
# this copy): every column but the key could be empty.
V0_2_SCHEMA = """
CREATE TABLE analyses (
    id VARCHAR(32) NOT NULL,
    created_at DATETIME,
    expires_at DATETIME,
    pipeline_version VARCHAR(32),
    file_type VARCHAR(8),
    file_sha256 VARCHAR(64),
    report_json TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX ix_analyses_expires_at ON analyses (expires_at);
"""

# Every table exactly as v0.5's create_all made it on SQLite (from commit 02c3195).
V0_5_SCHEMA = """
CREATE TABLE analyses (
    id VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    pipeline_version VARCHAR(32) NOT NULL,
    file_type VARCHAR(8) NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    report_json TEXT NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX ix_analyses_expires_at ON analyses (expires_at);
CREATE TABLE analysis_resumes (
    analysis_id VARCHAR(32) NOT NULL,
    resume_json TEXT NOT NULL,
    PRIMARY KEY (analysis_id),
    FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
CREATE TABLE suggestions (
    id VARCHAR(32) NOT NULL,
    analysis_id VARCHAR(32) NOT NULL,
    requirement_id VARCHAR(16) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    source_text TEXT NOT NULL,
    text TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    prompt_version VARCHAR(32) NOT NULL,
    model VARCHAR(64) NOT NULL,
    position INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
CREATE INDEX ix_suggestions_analysis_id ON suggestions (analysis_id);
CREATE TABLE suggestion_runs (
    id INTEGER NOT NULL,
    analysis_id VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    model VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(32) NOT NULL,
    calls INTEGER NOT NULL,
    requested INTEGER NOT NULL,
    returned INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    kept INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
CREATE INDEX ix_suggestion_runs_analysis_id ON suggestion_runs (analysis_id);
CREATE TABLE span_corrections (
    analysis_id VARCHAR(32) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    text TEXT NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (analysis_id, span_id),
    FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
CREATE TABLE gap_answers (
    analysis_id VARCHAR(32) NOT NULL,
    requirement_id VARCHAR(16) NOT NULL,
    answer TEXT NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (analysis_id, requirement_id),
    FOREIGN KEY(analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
"""
OLD_ID = "a" * 32
EXPIRED_ID = "e" * 32
SUGGESTION_ID = "b" * 32
legacy_only = pytest.mark.skipif(on_postgres(), reason="files from v0.5 and earlier are SQLite")


def _no_drift(engine: Engine) -> None:
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def _when(delta: timedelta) -> str:
    """A time as SQLAlchemy stored it in a SQLite DATETIME column."""
    return (datetime.now(UTC) + delta).replace(tzinfo=None).isoformat(sep=" ")


def test_upgrade_builds_the_schema_the_models_describe(empty_database_url: str) -> None:
    engine = make_engine(empty_database_url)
    try:
        assert schema_status(engine).current is None
        upgrade(engine)
        assert set(inspect(engine).get_table_names()) == TABLES
        _no_drift(engine)
        status = schema_status(engine)
        assert status.up_to_date and status.current == head_revision() and not status.legacy
        upgrade(engine)  # a second run changes nothing
        ensure_current(engine)
    finally:
        engine.dispose()


def test_downgrade_and_upgrade_again(empty_database_url: str) -> None:
    engine = make_engine(empty_database_url)
    config = alembic_config()
    try:
        upgrade(engine)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        upgrade(engine)
        assert set(inspect(engine).get_table_names()) == TABLES
    finally:
        engine.dispose()


def test_the_alembic_command_line_setup_works(
    empty_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`alembic upgrade head` from the project folder, reading DATABASE_URL."""
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    # alembic.ini's logging setup must leave the app's loggers working.
    assert not logging.getLogger("app").disabled
    engine = make_engine(empty_database_url)
    try:
        assert schema_status(engine).up_to_date
    finally:
        engine.dispose()


def test_offline_sql_has_every_table(
    empty_database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`alembic upgrade head --sql` writes the SQL for a DBA to run by hand."""
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head", sql=True)
    sql = capsys.readouterr().out
    for table in TABLES - {"alembic_version"}:
        assert f"CREATE TABLE {table} " in sql


def test_the_status_command(empty_database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", empty_database_url)
    out = io.StringIO()
    assert migrations.main([], out=out) == 1
    assert "Migrations are pending" in out.getvalue() and "no revision" in out.getvalue()
    engine = make_engine(empty_database_url)
    try:
        upgrade(engine)
    finally:
        engine.dispose()
    out = io.StringIO()
    assert migrations.main([], out=out) == 0
    assert f"revision {head_revision()}, the newest" in out.getvalue()


def test_check_mode_refuses_to_start_with_pending_migrations(
    empty_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(empty_database_url, db_auto_migrate=False, log_level="INFO")
    app = create_app(settings)
    logging.getLogger().addHandler(caplog.handler)
    with pytest.raises(StartupError, match="migrations are pending") as error, TestClient(app):
        pass  # pragma: no cover
    assert "alembic upgrade head" in str(error.value)
    assert any(r.getMessage() == "database not ready" for r in caplog.records)
    # Nothing was created.
    engine = make_engine(empty_database_url)
    try:
        assert "users" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_local_mode_migrates_at_startup(empty_database_url: str) -> None:
    settings = make_settings(empty_database_url)
    assert settings.auto_migrate
    with TestClient(create_app(settings)) as client:
        authenticate(client)
        assert client.get("/readyz").status_code == 200


def test_production_default_is_not_to_migrate() -> None:
    settings = make_settings("sqlite://", app_env="production")
    assert settings.auto_migrate is False
    assert make_settings("sqlite://", app_env="production", db_auto_migrate=True).auto_migrate


# ---------------------------------------------------------------------------
# Database files from v0.5 and earlier
# ---------------------------------------------------------------------------


def _old_report(markup: str, jd: str, version: str) -> tuple[str, str]:
    """A report and resume lines as an older version stored them."""
    resume, report = analyze(build_pdf(markup), jd)
    data = report.model_dump(mode="json")
    data["pipeline_version"] = version
    return json.dumps(data), resume.model_dump_json()


def _v0_2_report(markup: str, jd: str) -> str:
    """A current report with the fields v0.3 added removed, as v0.2 stored it."""
    report_json, _ = _old_report(markup, jd, "0.2.0-exact")
    data = json.loads(report_json)
    del data["job_parser"]
    for requirement in data["job"]["requirements"]:
        del requirement["free_text_skills"]
    for match in data["matches"]:
        del match["requirement"]["free_text_skills"]
    return json.dumps(data)


def _write_v0_5_file(path: Path, markup: str, jd: str) -> str:
    """A v0.5 database with one live analysis that has one of everything, and one
    expired analysis. Returns the text of the line that was corrected."""
    report_json, resume_json = _old_report(markup, jd, "0.5.0-exact")
    resume = json.loads(resume_json)
    span = next(s for s in resume["spans"] if s["kind"] == "bullet")
    now, later = _when(timedelta()), _when(timedelta(hours=12))
    with sqlite3.connect(path) as conn:
        conn.executescript(V0_5_SCHEMA)
        for analysis_id, expires in ((OLD_ID, later), (EXPIRED_ID, _when(-timedelta(hours=1)))):
            conn.execute(
                "INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)",
                (analysis_id, now, expires, "0.5.0-exact", "pdf", "0" * 64, report_json),
            )
            conn.execute("INSERT INTO analysis_resumes VALUES (?, ?)", (analysis_id, resume_json))
        conn.execute(
            "INSERT INTO suggestions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                SUGGESTION_ID,
                OLD_ID,
                "r6",
                span["id"],
                span["text"],
                "A rewrite accepted in v0.5.",
                "accepted",
                "rewrite_v1",
                "claude-sonnet-5-5",
                0,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO suggestion_runs VALUES (1, ?, ?, 'claude-sonnet-5-5', 'rewrite_v1', "
            "1, 2, 2, 1, 1, 900, 120)",
            (OLD_ID, now),
        )
        conn.execute(
            "INSERT INTO span_corrections VALUES (?, 's3', 'A corrected line from v0.5.', ?)",
            (OLD_ID, now),
        )
        conn.execute(
            "INSERT INTO gap_answers VALUES (?, 'r11', 'An answer from v0.5.', ?)", (OLD_ID, now)
        )
    conn.close()
    return str(span["text"])


@legacy_only
def test_a_v0_5_database_still_starts_with_everything_kept(
    tmp_path: Path, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    path = tmp_path / "v05.db"
    original = _write_v0_5_file(path, data_engineer_markup, data_engineer_jd)
    url = f"sqlite:///{path}"

    # Production's check mode doesn't change it, and says what to run.
    with (
        pytest.raises(StartupError, match=r"tables from v0\.5 or earlier") as error,
        TestClient(create_app(make_settings(url, db_auto_migrate=False))),
    ):
        pass  # pragma: no cover
    assert "alembic upgrade head" in str(error.value)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone() == (2,)

    # v0.5 had no login, so its analyses go to the local account AUTH_MODE=disabled uses.
    settings = make_settings(url, auth_mode="disabled", max_upload_mb=5)
    app = create_app(settings)
    with TestClient(app) as client:
        engine = app.state.db.engine
        assert set(inspect(engine).get_table_names()) == TABLES
        assert schema_status(engine).up_to_date
        _no_drift(engine)

        listed = client.get("/api/v1/analyses").json()["analyses"]
        assert [a["id"] for a in listed] == [OLD_ID]  # the expired one wasn't listed
        old = client.get(f"/api/v1/analyses/{OLD_ID}")
        assert old.status_code == 200, old.text
        assert old.json()["report"]["pipeline_version"] == "0.5.0-exact"
        spans = {s["id"]: s for s in client.get(f"/api/v1/analyses/{OLD_ID}/spans").json()["spans"]}
        assert spans["s3"]["text"] == "A corrected line from v0.5."
        [suggestion] = client.get(f"/api/v1/analyses/{OLD_ID}/suggestions").json()["suggestions"]
        assert suggestion["status"] == "accepted" and suggestion["original"] == original
        usage = client.get(f"/api/v1/analyses/{OLD_ID}/suggestions").json()["usage"]
        assert usage["requested"] == 2 and usage["rejected"] == 1
        questions = client.get(f"/api/v1/analyses/{OLD_ID}/gap-questions").json()["questions"]
        assert {q["requirement_id"]: q["answer"] for q in questions}["r11"] == (
            "An answer from v0.5."
        )
        changes = client.get(f"/api/v1/analyses/{OLD_ID}/export/changes").json()["changes"]
        assert {c["kind"] for c in changes} == {"correction", "rewrite"}
        assert client.get(f"/api/v1/analyses/{OLD_ID}/export.docx").status_code == 200

        new = client.post(
            "/api/v1/analyses",
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
            data={"job_description": data_engineer_jd, "consent": "true"},
        )
        assert new.status_code == 201
        assert client.delete(f"/api/v1/analyses/{OLD_ID}").status_code == 204

    # With login on, nobody else sees the old analysis, and nobody can log in as its owner.
    with TestClient(create_app(make_settings(url))) as client:
        authenticate(client)
        assert client.get(f"/api/v1/analyses/{new.json()['id']}").status_code == 404
        local = client.post("/api/v1/auth/login", json={"email": "local", "password": "!"})
        assert local.status_code == 401


@legacy_only
def test_a_v0_2_database_still_starts(
    tmp_path: Path, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    path = tmp_path / "v02.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(V0_2_SCHEMA)
        conn.execute(
            "INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                OLD_ID,
                _when(timedelta()),
                _when(timedelta(hours=12)),
                "0.2.0-exact",
                "pdf",
                "0" * 64,
                _v0_2_report(data_engineer_markup, data_engineer_jd),
            ),
        )
        # v0.2's columns allowed empty values. Such a row is left out, not guessed at.
        conn.execute("INSERT INTO analyses (id) VALUES (?)", ("f" * 32,))
    conn.close()

    settings = make_settings(f"sqlite:///{path}", auth_mode="disabled", max_upload_mb=5)
    app = create_app(settings)
    with TestClient(app) as client:
        _no_drift(app.state.db.engine)
        assert [a["id"] for a in client.get("/api/v1/analyses").json()["analyses"]] == [OLD_ID]
        old = client.get(f"/api/v1/analyses/{OLD_ID}")
        assert old.status_code == 200, old.text
        assert old.json()["report"]["job_parser"]["name"] == "rules"

        # Its lines weren't stored, so the features that need them say so.
        for url in ("spans", "export.docx", "export/changes"):
            response = client.get(f"/api/v1/analyses/{OLD_ID}/{url}")
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "resume_not_stored"
        # Gap questions only need the report.
        questions = client.get(f"/api/v1/analyses/{OLD_ID}/gap-questions").json()["questions"]
        assert {q["requirement_text"] for q in questions} == {
            "Experience with dbt",
            "Kafka or other streaming tools",
        }

        new = client.post(
            "/api/v1/analyses",
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
            data={"job_description": data_engineer_jd, "consent": "true"},
        )
        assert new.status_code == 201
        assert client.get(f"/api/v1/analyses/{new.json()['id']}/spans").status_code == 200
        assert client.delete(f"/api/v1/analyses/{OLD_ID}").status_code == 204
        me = client.get("/api/v1/auth/me").json()
        assert me["id"] == LOCAL_USER_ID


@legacy_only
def test_an_empty_v0_5_database_gets_no_local_account(tmp_path: Path) -> None:
    path = tmp_path / "empty-v05.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(V0_5_SCHEMA)
    conn.close()
    engine = make_engine(f"sqlite:///{path}")
    try:
        assert schema_status(engine).legacy_upgradable
        upgrade(engine)
        _no_drift(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar() == 0
    finally:
        engine.dispose()


@pytest.mark.skipif(not on_postgres(), reason="needs TEST_DATABASE_URL (CI's Postgres job)")
def test_v0_5_tables_on_postgres_are_refused(empty_database_url: str) -> None:
    engine = make_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE analyses (id VARCHAR(32) PRIMARY KEY)"))
        assert schema_status(engine).legacy and not schema_status(engine).legacy_upgradable
        for check in (upgrade, ensure_current):
            with pytest.raises(StartupError, match="isn't SQLite"):
                check(engine)
        config = alembic_config()
        with pytest.raises(RuntimeError, match="isn't SQLite"), engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        assert "users" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_the_consent_revision_keeps_every_row(empty_database_url: str) -> None:
    """0002 adds the consent columns to an analysis made at 0001, and taking it back
    off keeps the analysis and the rows stored with it."""
    engine = make_engine(empty_database_url)
    config = alembic_config()
    # Strings, as the stored timestamps are written by hand here.
    now, later = _when(timedelta(0)), _when(timedelta(hours=24))

    def migrate(action: Any, target: str) -> None:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            action(config, target)

    def count(table: str) -> int:
        with engine.connect() as connection:
            return int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())

    try:
        migrate(command.upgrade, "0001")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, created_at) "
                    "VALUES ('u1', 'person@example.com', '!', :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO analyses (id, owner_id, created_at, expires_at, "
                    "pipeline_version, file_type, file_sha256, report_json) VALUES "
                    "(:id, 'u1', :now, :later, '1.0.0-exact', 'pdf', :sha, '{}')"
                ),
                {"id": OLD_ID, "now": now, "later": later, "sha": "0" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO gap_answers (analysis_id, requirement_id, answer, updated_at) "
                    "VALUES (:id, 'r1', 'No.', :now)"
                ),
                {"id": OLD_ID, "now": now},
            )
        upgrade(engine)
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT consent_at, consent_version, llm_consent FROM analyses")
            ).one()
        assert (row[0], row[1], bool(row[2])) == (None, None, False)
        migrate(command.downgrade, "0001")
        columns = {c["name"] for c in inspect(engine).get_columns("analyses")}
        assert not columns & {"consent_at", "consent_version", "llm_consent"}
        assert (count("analyses"), count("gap_answers")) == (1, 1)
    finally:
        engine.dispose()
