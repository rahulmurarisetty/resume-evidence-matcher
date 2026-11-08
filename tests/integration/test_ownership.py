"""Each person sees only their own analyses, and deleting an account deletes all of
its data at once while leaving everyone else's alone."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.storage.db import (
    AnalysisRecord,
    AuthSessionRecord,
    Base,
    CorrectionRecord,
    Database,
    GapAnswerRecord,
    ResumeRecord,
    SuggestionRecord,
    SuggestionRunRecord,
    UserRecord,
)
from tests.builders import build_pdf
from tests.fakes import FakeLLMClient
from tests.integration.test_edits_api import rewrite_handler
from tests.support import bearer, login, make_settings, register

BASE = "/api/v1/analyses"
PDF = "application/pdf"
ALICE, BOB = "alice@example.com", "bob@example.com"


@pytest.fixture
def two_people(database_url: str) -> Iterator[tuple[TestClient, Settings, str, str]]:
    settings = make_settings(database_url, llm_enabled="on", max_upload_mb=5)
    fake = FakeLLMClient(handler=rewrite_handler)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        register(client, ALICE)
        register(client, BOB)
        yield client, settings, login(client, ALICE), login(client, BOB)


def _create(client: TestClient, token: str, markup: str, jd: str) -> str:
    response = client.post(
        BASE,
        files={"resume": ("r.pdf", build_pdf(markup), PDF)},
        data={"job_description": jd, "consent": "true", "llm_consent": "true"},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _fill(client: TestClient, token: str, analysis_id: str) -> None:
    """One of everything an analysis can have."""
    headers = bearer(token)
    [suggestion, *_] = client.post(
        f"{BASE}/{analysis_id}/suggestions", json={"requirement_ids": ["r6"]}, headers=headers
    ).json()["suggestions"]
    client.post(f"{BASE}/{analysis_id}/suggestions/{suggestion['id']}/accept", headers=headers)
    client.patch(f"{BASE}/{analysis_id}/spans/s3", json={"text": "Fixed line."}, headers=headers)
    client.put(f"{BASE}/{analysis_id}/gap-answers/r11", json={"answer": "No."}, headers=headers)


def _counts(settings: Settings) -> dict[str, int]:
    tables: tuple[type[Base], ...] = (
        UserRecord,
        AuthSessionRecord,
        AnalysisRecord,
        ResumeRecord,
        SuggestionRecord,
        SuggestionRunRecord,
        CorrectionRecord,
        GapAnswerRecord,
    )
    db = Database(settings.database_url)
    try:
        for session in db.session():
            return {
                str(t.__tablename__): int(session.scalar(select(func.count()).select_from(t)) or 0)
                for t in tables
            }
    finally:
        db.engine.dispose()
    raise AssertionError("no session")  # pragma: no cover


CALLS: list[Callable[[TestClient, str, dict[str, str]], Any]] = [
    lambda c, a, h: c.get(f"{BASE}/{a}", headers=h),
    lambda c, a, h: c.delete(f"{BASE}/{a}", headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/suggestions", headers=h),
    lambda c, a, h: c.post(f"{BASE}/{a}/suggestions", json={}, headers=h),
    lambda c, a, h: c.post(f"{BASE}/{a}/suggestions/x/accept", headers=h),
    lambda c, a, h: c.post(f"{BASE}/{a}/suggestions/x/reject", headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/spans", headers=h),
    lambda c, a, h: c.patch(f"{BASE}/{a}/spans/s3", json={"text": "x"}, headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/gap-questions", headers=h),
    lambda c, a, h: c.put(f"{BASE}/{a}/gap-answers/r11", json={"answer": "x"}, headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/export.docx", headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/export/changes", headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/report.html", headers=h),
    lambda c, a, h: c.get(f"{BASE}/{a}/report.md", headers=h),
]


@pytest.mark.parametrize("call", CALLS)
def test_another_persons_analysis_is_404(
    two_people: tuple[TestClient, Settings, str, str],
    call: Callable[[TestClient, str, dict[str, str]], Any],
    data_engineer_markup: str,
    data_engineer_jd: str,
) -> None:
    client, settings, alice, bob = two_people
    analysis_id = _create(client, alice, data_engineer_markup, data_engineer_jd)
    before = _counts(settings)
    response = call(client, analysis_id, bearer(bob))
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    # Nothing Bob tried changed Alice's analysis, and she still sees it.
    assert _counts(settings) == before
    assert client.get(f"{BASE}/{analysis_id}", headers=bearer(alice)).status_code == 200


def test_the_list_shows_only_your_own(
    two_people: tuple[TestClient, Settings, str, str],
    data_engineer_markup: str,
    data_engineer_jd: str,
    dotnet_markup: str,
    dotnet_jd: str,
) -> None:
    client, _, alice, bob = two_people
    first = _create(client, alice, data_engineer_markup, data_engineer_jd)
    second = _create(client, alice, dotnet_markup, dotnet_jd)
    theirs = _create(client, bob, data_engineer_markup, data_engineer_jd)
    listed = client.get(BASE, headers=bearer(alice)).json()["analyses"]
    assert [a["id"] for a in listed] == [second, first]  # newest first
    assert listed[1]["required"]["direct"] == 5
    assert listed[1]["pipeline_version"] == "1.0.0-exact"
    assert [a["id"] for a in client.get(BASE, headers=bearer(bob)).json()["analyses"]] == [theirs]


def test_deleting_an_account_deletes_all_of_its_data(
    two_people: tuple[TestClient, Settings, str, str],
    data_engineer_markup: str,
    data_engineer_jd: str,
) -> None:
    client, settings, alice, bob = two_people
    for token in (alice, bob):
        _fill(client, token, _create(client, token, data_engineer_markup, data_engineer_jd))
    _create(client, alice, data_engineer_markup, data_engineer_jd)
    second_alice_session = login(client, ALICE)
    assert _counts(settings) == {
        "users": 2,
        "sessions": 3,
        "analyses": 3,
        "analysis_resumes": 3,
        "suggestions": 2,
        "suggestion_runs": 2,
        "span_corrections": 2,
        "gap_answers": 2,
    }

    assert client.delete("/api/v1/auth/me", headers=bearer(alice)).status_code == 204
    # Bob's rows are all that is left: his account, session and one filled analysis.
    assert _counts(settings) == {
        "users": 1,
        "sessions": 1,
        "analyses": 1,
        "analysis_resumes": 1,
        "suggestions": 1,
        "suggestion_runs": 1,
        "span_corrections": 1,
        "gap_answers": 1,
    }
    for token in (alice, second_alice_session):
        assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    failed = client.post(
        "/api/v1/auth/login", json={"email": ALICE, "password": "correct horse battery staple"}
    )
    assert failed.status_code == 401
    assert len(client.get(BASE, headers=bearer(bob)).json()["analyses"]) == 1
