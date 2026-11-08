"""Consent before an analysis, consent for Claude, metric questions and the
downloadable match report, through the API."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.claude_jd_parser import ClaudeJobOutput
from app.services.consent import CONSENT_VERSION, consent_notice
from app.storage.db import AnalysisRecord, Database
from tests.builders import build_pdf
from tests.fakes import FakeLLMClient
from tests.integration.test_edits_api import rewrite_handler
from tests.support import authenticate, bearer, login, make_settings, register

PDF = "application/pdf"
BASE = "/api/v1/analyses"


def _post(client: TestClient, markup: str, jd: str, **fields: str) -> Any:
    return client.post(
        BASE,
        files={"resume": ("resume.pdf", build_pdf(markup), PDF)},
        data={"job_description": jd, **fields},
    )


@pytest.fixture
def claude_on(database_url: str) -> Iterator[tuple[TestClient, FakeLLMClient]]:
    fake = FakeLLMClient(handler=rewrite_handler, model="claude-sonnet-5-5")
    settings = make_settings(database_url, llm_enabled="on", max_upload_mb=5)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        authenticate(client)
        yield client, fake


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "false", "0"])
def test_an_analysis_needs_consent(
    client: TestClient,
    settings: Settings,
    data_engineer_markup: str,
    data_engineer_jd: str,
    value: str | None,
) -> None:
    fields = {"consent": value} if value is not None else {}
    response = _post(client, data_engineer_markup, data_engineer_jd, **fields)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "consent_required"
    assert "Tick the box" in error["message"] and "Nothing was read or stored" in error["message"]
    assert client.get(BASE).json()["analyses"] == []


def test_consent_is_stored_with_the_analysis(
    client: TestClient, settings: Settings, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    response = _post(client, data_engineer_markup, data_engineer_jd, consent="true")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["consent"]["version"] == CONSENT_VERSION
    assert body["consent"]["given_at"] is not None
    # Claude is off on this server, so no consent for it is stored.
    assert body["consent"]["llm"] is False
    again = client.get(f"{BASE}/{body['id']}").json()
    assert again["consent"] == body["consent"]

    database = Database(settings.database_url)
    try:
        session = next(database.session())
        record = session.get(AnalysisRecord, body["id"])
        assert record is not None
        assert record.consent_version == CONSENT_VERSION and record.consent_at is not None
        assert record.llm_consent is False
        session.close()
    finally:
        database.engine.dispose()


def test_llm_consent_given_while_claude_is_off_is_stored_as_false(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    body = _post(
        client, data_engineer_markup, data_engineer_jd, consent="true", llm_consent="true"
    ).json()
    assert body["consent"]["llm"] is False
    assert body["report"]["job_parser"]["name"] == "rules"


def test_without_llm_consent_claude_sees_nothing(
    claude_on: tuple[TestClient, FakeLLMClient], data_engineer_markup: str, data_engineer_jd: str
) -> None:
    client, fake = claude_on
    body = _post(client, data_engineer_markup, data_engineer_jd, consent="true").json()
    # Claude is on, but the person didn't agree: the rules read the job description.
    assert fake.calls == []
    assert body["report"]["job_parser"] == {
        "name": "rules",
        "prompt_version": None,
        "model": None,
        "fallback_reason": None,
        "dropped_requirements": 0,
    }
    assert body["consent"]["llm"] is False
    response = client.post(f"{BASE}/{body['id']}/suggestions", json={"requirement_ids": ["r6"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "llm_consent_required"
    assert "llm_consent=true" in response.json()["error"]["message"]
    assert fake.calls == []


def test_with_llm_consent_claude_is_used(
    claude_on: tuple[TestClient, FakeLLMClient], data_engineer_markup: str, data_engineer_jd: str
) -> None:
    client, fake = claude_on
    body = _post(
        client, data_engineer_markup, data_engineer_jd, consent="true", llm_consent="true"
    ).json()
    assert body["consent"]["llm"] is True
    assert [c.output_type for c in fake.calls] == [ClaudeJobOutput]  # the parse was tried
    response = client.post(f"{BASE}/{body['id']}/suggestions", json={"requirement_ids": ["r6"]})
    assert response.status_code == 200, response.text


def test_the_consent_notice_follows_the_settings(
    client: TestClient, claude_on: tuple[TestClient, FakeLLMClient]
) -> None:
    notice = client.get("/api/v1/consent").json()
    assert notice["version"] == CONSENT_VERSION
    text = " ".join(notice["points"])
    assert "24 hours" in text and "Only your account can see" in text
    assert "doesn't scan uploads" in text  # SCANNER=off in the tests
    assert notice["llm_available"] is False
    assert notice["llm_points"] == [] and notice["llm_checkbox"] is None

    with_claude = claude_on[0].get("/api/v1/consent").json()
    assert with_claude["llm_available"] is True
    claude_text = " ".join(with_claude["llm_points"])
    assert "Anthropic" in claude_text and "never sent" in claude_text
    assert "(optional)" in with_claude["llm_checkbox"]


def test_the_notice_says_when_uploads_are_scanned(settings: Settings) -> None:
    scanned = consent_notice(settings, llm_available=False, scanning=True)
    assert "Every upload is scanned for malware before it is read." in scanned.points
    one_hour = consent_notice(
        settings.model_copy(update={"retention_hours": 1}), llm_available=False, scanning=True
    )
    assert "deleted 1 hour after" in " ".join(one_hour.points)


def test_the_consent_notice_needs_a_login(database_url: str) -> None:
    with TestClient(create_app(make_settings(database_url))) as client:
        assert client.get("/api/v1/consent").status_code == 401


# ---------------------------------------------------------------------------
# Metric questions and the match report
# ---------------------------------------------------------------------------


@pytest.fixture
def analysis_id(client: TestClient, data_engineer_markup: str, data_engineer_jd: str) -> str:
    response = _post(client, data_engineer_markup, data_engineer_jd, consent="true")
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_metric_questions_are_listed_and_answered(client: TestClient, analysis_id: str) -> None:
    url = f"{BASE}/{analysis_id}"
    questions = client.get(f"{url}/gap-questions").json()["questions"]
    metric = [q for q in questions if q["kind"] == "metric"]
    assert 0 < len(metric) <= 5
    first = metric[0]
    assert first["id"] == f"metric-{first['span_id']}"
    assert first["line"] and first["line"] in first["question"]
    assert first["question"].endswith(
        "How many, how much, how fast or how often? Add a number only if you know it."
    )
    saved = client.put(f"{url}/gap-answers/{first['id']}", json={"answer": "About 20 tables."})
    assert saved.status_code == 200 and saved.json()["answer"] == "About 20 tables."
    assert saved.json()["kind"] == "metric"
    # The answer never goes into the resume.
    spans = client.get(f"{url}/spans").json()["spans"]
    assert all("20 tables" not in s["text"] for s in spans)
    assert client.get(f"{url}/export/changes").json()["changes"] == []
    missing = client.put(f"{url}/gap-answers/metric-s999", json={"answer": "5"})
    assert missing.status_code == 404


def test_report_downloads(client: TestClient, analysis_id: str) -> None:
    url = f"{BASE}/{analysis_id}"
    question = next(
        q for q in client.get(f"{url}/gap-questions").json()["questions"] if q["kind"] == "gap"
    )
    client.put(f"{url}/gap-answers/{question['id']}", json={"answer": "Only in a course."})

    page = client.get(f"{url}/report.html")
    assert page.status_code == 200
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert page.headers["content-disposition"] == 'attachment; filename="match-report.html"'
    assert page.headers["cache-control"] == "no-store"
    csp = page.headers["content-security-policy"]
    assert csp.startswith("default-src 'none'; style-src 'sha256-")
    assert "script-src" not in csp and "unsafe-inline" not in csp
    assert '<html lang="en">' in page.text and "<script" not in page.text
    assert "Only in a course." in page.text

    markdown = client.get(f"{url}/report.md")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"] == "text/markdown; charset=utf-8"
    assert markdown.text.startswith("# Match report: Senior Data Engineer\n")
    assert "no universal ATS score" in markdown.text
    assert "## Section order advice" in markdown.text


def test_reports_are_for_the_owner_only(client: TestClient, analysis_id: str) -> None:
    register(client, "other@example.com")
    other = bearer(login(client, "other@example.com"))
    for path in ("report.html", "report.md"):
        response = client.get(f"{BASE}/{analysis_id}/{path}", headers=other)
        assert response.status_code == 404
        anonymous = client.get(f"{BASE}/{analysis_id}/{path}", headers={"Authorization": ""})
        assert anonymous.status_code == 401
