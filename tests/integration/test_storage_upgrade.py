"""A database file written by v0.2 must still start. v0.3 only adds tables."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import Settings
from app.main import create_app
from app.services.analysis import analyze
from tests.builders import build_pdf

# The analyses table exactly as v0.2's create_all made it on SQLite.
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
OLD_ID = "a" * 32


def _v0_2_report(markup: str, jd: str) -> str:
    """A current report with the v0.3 fields removed, as v0.2 stored it."""
    _, report = analyze(build_pdf(markup), jd)
    data = report.model_dump(mode="json")
    data["pipeline_version"] = "0.2.0-exact"
    del data["job_parser"]
    for requirement in data["job"]["requirements"]:
        del requirement["free_text_skills"]
    for match in data["matches"]:
        del match["requirement"]["free_text_skills"]
    return json.dumps(data)


def test_v0_2_database_starts_and_old_analyses_still_work(
    tmp_path: Path, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    path = tmp_path / "v02.db"
    now = datetime.now(UTC).replace(tzinfo=None)
    with sqlite3.connect(path) as conn:
        conn.executescript(V0_2_SCHEMA)
        conn.execute(
            "INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                OLD_ID,
                now.isoformat(sep=" "),
                (now + timedelta(hours=12)).isoformat(sep=" "),
                "0.2.0-exact",
                "pdf",
                "0" * 64,
                _v0_2_report(data_engineer_markup, data_engineer_jd),
            ),
        )
    conn.close()

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=f"sqlite:///{path}",
        log_level="WARNING",
        semantic_matching="off",
        llm_enabled="off",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        tables = set(inspect(app.state.db.engine).get_table_names())
        assert {
            "analyses",
            "analysis_resumes",
            "suggestions",
            "suggestion_runs",
            "span_corrections",
            "gap_answers",
        } <= tables

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
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), "application/pdf")},
            data={"job_description": data_engineer_jd},
        )
        assert new.status_code == 201
        spans = client.get(f"/api/v1/analyses/{new.json()['id']}/spans")
        assert spans.status_code == 200

        assert client.delete(f"/api/v1/analyses/{OLD_ID}").status_code == 204
