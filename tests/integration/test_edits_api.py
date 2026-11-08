"""Suggestions, corrections, gap answers and export through the API. Claude is a
fake: the job-description call times out (so the rule parser runs and ids are
stable) and rewrite calls return one faithful and one invented candidate."""

import io
import logging
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMError, LLMTimeoutError
from app.main import create_app
from app.models import AnalysisReport, FileType
from app.services.claude_jd_parser import ClaudeJobOutput
from app.services.rewrite import RewriteOutput
from app.storage.db import Database
from app.storage.repository import AnalysisRepository
from tests.builders import build_pdf
from tests.fakes import FakeLLMClient, LLMCall

PDF = "application/pdf"
BASE = "/api/v1/analyses"
# The sample bullets the tests rewrite, and a faithful rewrite of each.
FAITHFUL = {
    "Wrote Python data-quality checks that run before every load and block bad files from "
    "reaching reporting tables.": (
        "Wrote Python data-quality checks that block bad files from reaching reporting tables.",
        "Built Python data-quality checks that run before every load.",
    ),
    "Scheduled and monitored 40+ Airflow DAGs, adding SLA alerts that reduced missed morning "
    "loads from weekly to roughly once a quarter.": (
        "Orchestrated and monitored 40+ Airflow DAGs with SLA alerts.",
        "Monitored 40+ Airflow DAGs with SLA alerts.",
    ),
}


def _bullet(call: LLMCall) -> str:
    return call.user.split("<bullet>\n", 1)[1].split("\n</bullet>", 1)[0]


def rewrite_handler(call: LLMCall) -> object:
    if call.output_type is ClaudeJobOutput:
        raise LLMTimeoutError("the parse isn't under test here")
    bullet = _bullet(call)
    faithful = FAITHFUL.get(bullet, (bullet.split(", ")[0].rstrip(".") + ".",))[0]
    invented = f"{bullet.rstrip('.')} for Placeholder Bank in 2021."
    return RewriteOutput(rewrites=[faithful, invented])


def _settings(tmp_path: Path, **values: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": f"sqlite:///{tmp_path / 'edits.db'}",
        "log_level": "WARNING",
        "semantic_matching": "off",
        "llm_enabled": "on",
    }
    return Settings(_env_file=None, **(base | values))  # type: ignore[call-arg]


@pytest.fixture
def fake() -> FakeLLMClient:
    return FakeLLMClient(handler=rewrite_handler, model="claude-sonnet-5-5")


@pytest.fixture
def llm_client(tmp_path: Path, fake: FakeLLMClient) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(tmp_path), llm_client=fake)) as test_client:
        yield test_client


def _create(client: TestClient, markup: str, jd: str) -> dict[str, Any]:
    response = client.post(
        BASE,
        files={"resume": ("resume.pdf", build_pdf(markup), PDF)},
        data={"job_description": jd},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def analysis(llm_client: TestClient, data_engineer_markup: str, data_engineer_jd: str) -> str:
    body = _create(llm_client, data_engineer_markup, data_engineer_jd)
    report = body["report"]
    assert report["job_parser"]["name"] == "rules"
    assert report["job_parser"]["fallback_reason"] == "timeout"
    return str(body["id"])


def _suggest(client: TestClient, analysis_id: str, ids: list[str] | None = None) -> Any:
    body = {"requirement_ids": ids} if ids is not None else None
    return client.post(f"{BASE}/{analysis_id}/suggestions", json=body)


def _error(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_suggest_accept_correct_and_export(
    llm_client: TestClient, analysis: str, fake: FakeLLMClient
) -> None:
    response = _suggest(llm_client, analysis, ["r6", "r2"])
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["returned"] == 4
    assert batch["rejected"] == 2  # the invented candidates
    assert batch["usage"] == {"requested": 4, "limit": 20, "remaining": 16, "rejected": 2}
    suggestions = batch["suggestions"]
    assert [(s["requirement_id"], s["span_id"]) for s in suggestions] == [
        ("r2", "s8"),
        ("r6", "s9"),
    ]
    assert all(s["status"] == "proposed" and s["kind"] == "rewrite" for s in suggestions)
    assert all(s["prompt_version"] == "rewrite_v1" for s in suggestions)
    assert all(s["model"] == "claude-sonnet-5-5" for s in suggestions)
    assert all("Placeholder Bank" not in s["text"] for s in suggestions)
    airflow, python = suggestions
    assert airflow["original"].startswith("Scheduled and monitored 40+ Airflow DAGs")
    rewrite_calls = [c for c in fake.calls if c.output_type is RewriteOutput]
    assert [c.model for c in rewrite_calls] == ["claude-sonnet-5-5", "claude-sonnet-5-5"]

    listed = llm_client.get(f"{BASE}/{analysis}/suggestions").json()
    assert [s["id"] for s in listed["suggestions"]] == [airflow["id"], python["id"]]
    assert listed["usage"]["requested"] == 4

    accepted = llm_client.post(f"{BASE}/{analysis}/suggestions/{python['id']}/accept")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    rejected = llm_client.post(f"{BASE}/{analysis}/suggestions/{airflow['id']}/reject")
    assert rejected.json()["status"] == "rejected"

    summary = "Data engineer with six years of experience building batch pipelines."
    corrected = llm_client.patch(f"{BASE}/{analysis}/spans/s3", json={"text": summary})
    assert corrected.status_code == 200
    assert corrected.json()["source"] == "user_correction"
    spans = {s["id"]: s for s in llm_client.get(f"{BASE}/{analysis}/spans").json()["spans"]}
    assert spans["s3"]["text"] == summary
    assert spans["s3"]["original_text"].startswith("Data engineer with six years")
    assert spans["s4"]["source"] == "extracted"

    changes = llm_client.get(f"{BASE}/{analysis}/export/changes").json()["changes"]
    assert [(c["span_id"], c["kind"], c["label"]) for c in changes] == [
        ("s3", "correction", "User correction"),
        ("s9", "rewrite", "Accepted rewrite"),
    ]
    assert changes[1]["before"] == python["original"]
    assert changes[1]["after"] == python["text"]
    assert changes[1]["suggestion_id"] == python["id"]

    export = llm_client.get(f"{BASE}/{analysis}/export.docx")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in export.headers["content-disposition"]
    assert export.headers["cache-control"] == "no-store"
    doc = Document(io.BytesIO(export.content))
    texts = [p.text for p in doc.paragraphs]
    assert summary in texts
    assert python["text"] in texts and python["original"] not in texts
    assert airflow["text"] not in texts and airflow["original"] in texts
    assert doc.tables == []


def test_one_accepted_rewrite_per_line(llm_client: TestClient, analysis: str) -> None:
    # Ask twice for r6 so one line has two suggestions.
    first = _suggest(llm_client, analysis, ["r6"]).json()["suggestions"]
    [a] = first
    accept = f"{BASE}/{analysis}/suggestions/{{}}/accept"
    assert llm_client.post(accept.format(a["id"])).status_code == 200
    # Accepting again is a no-op.
    assert llm_client.post(accept.format(a["id"])).json()["status"] == "accepted"

    fake_second = "Wrote Python checks that block bad files before every load."
    other = llm_client.app.state.llm  # type: ignore[attr-defined]
    other.handler = lambda call: RewriteOutput(rewrites=[fake_second])
    [b] = _suggest(llm_client, analysis, ["r6"]).json()["suggestions"]
    assert b["span_id"] == a["span_id"]
    conflict = llm_client.post(accept.format(b["id"]))
    assert conflict.status_code == 409 and _error(conflict) == "line_has_accepted_rewrite"

    # A line with an accepted rewrite can't be corrected until the rewrite is rejected.
    patch = llm_client.patch(f"{BASE}/{analysis}/spans/{a['span_id']}", json={"text": "x y z"})
    assert patch.status_code == 409 and _error(patch) == "line_has_accepted_rewrite"
    llm_client.post(f"{BASE}/{analysis}/suggestions/{a['id']}/reject")
    assert llm_client.post(accept.format(b["id"])).status_code == 200


def test_a_suggestion_for_a_changed_line_cant_be_accepted(
    llm_client: TestClient, analysis: str, fake: FakeLLMClient
) -> None:
    [s] = _suggest(llm_client, analysis, ["r6"]).json()["suggestions"]
    fixed = "Wrote Python data quality checks that run before every load."
    llm_client.patch(f"{BASE}/{analysis}/spans/{s['span_id']}", json={"text": fixed})
    response = llm_client.post(f"{BASE}/{analysis}/suggestions/{s['id']}/accept")
    assert response.status_code == 409 and _error(response) == "line_changed"

    # New suggestions are made from the corrected line.
    fake.handler = lambda call: RewriteOutput(rewrites=["Wrote Python data quality checks."])
    [new] = _suggest(llm_client, analysis, ["r6"]).json()["suggestions"]
    assert new["original"] == fixed
    assert _bullet(fake.calls[-1]) == fixed


def test_all_eligible_requirements(
    llm_client: TestClient, analysis: str, fake: FakeLLMClient
) -> None:
    batch = _suggest(llm_client, analysis).json()
    skipped = {s["requirement_id"]: s["reason"] for s in batch["skipped"]}
    # Git, CI/CD and Kubernetes are only in the skills list, and "Insurance" only in a
    # role header line, so none has a bullet to rewrite.
    assert skipped == {"r10": "no_bullet", "r13": "no_bullet", "r14": "no_bullet"}
    made = {s["requirement_id"] for s in batch["suggestions"]}
    # r8 and r9 pick the same bullets as r7 and r0, and the fake answers with the same
    # text, so their repeats are dropped.
    assert len([c for c in fake.calls if c.output_type is RewriteOutput]) == 6
    assert made == {"r0", "r2", "r6", "r7"}
    again = _suggest(llm_client, analysis).json()
    assert again["suggestions"] == []
    assert {s["reason"] for s in again["skipped"]} == {"already_suggested", "no_bullet"}


def test_the_cap_is_respected(
    tmp_path: Path, fake: FakeLLMClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    app = create_app(_settings(tmp_path, llm_max_suggestions=3), llm_client=fake)
    with TestClient(app) as client:
        analysis_id = _create(client, data_engineer_markup, data_engineer_jd)["id"]
        batch = _suggest(client, analysis_id).json()
        # Two candidates for the first requirement, one for the second, then the cap.
        assert batch["usage"] == {"requested": 3, "limit": 3, "remaining": 0, "rejected": 1}
        assert len([c for c in fake.calls if c.output_type is RewriteOutput]) == 2
        assert "limit_reached" in {s["reason"] for s in batch["skipped"]}
        response = _suggest(client, analysis_id, ["r6"])
        assert response.status_code == 409
        assert _error(response) == "suggestion_limit_reached"


def test_409_when_claude_is_off(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    analysis_id = _create(client, data_engineer_markup, data_engineer_jd)["id"]
    response = _suggest(client, analysis_id)
    assert response.status_code == 409
    assert _error(response) == "llm_disabled"
    assert "ANTHROPIC_API_KEY" in response.json()["error"]["message"]
    # Everything else works without Claude.
    assert client.get(f"{BASE}/{analysis_id}/suggestions").json()["suggestions"] == []
    assert client.get(f"{BASE}/{analysis_id}/export.docx").status_code == 200
    assert client.get(f"{BASE}/{analysis_id}/gap-questions").status_code == 200


def test_off_ignores_an_injected_client(tmp_path: Path, fake: FakeLLMClient) -> None:
    app = create_app(_settings(tmp_path, llm_enabled="off"), llm_client=fake)
    with TestClient(app):
        assert app.state.llm is None


def test_unknown_requirement_is_422(llm_client: TestClient, analysis: str) -> None:
    response = _suggest(llm_client, analysis, ["r6", "r99"])
    assert response.status_code == 422
    assert _error(response) == "unknown_requirement"


def test_503_when_claude_fails(llm_client: TestClient, analysis: str, fake: FakeLLMClient) -> None:
    fake.handler = lambda call: LLMError("down")
    response = _suggest(llm_client, analysis, ["r6", "r2"])
    assert response.status_code == 503
    assert _error(response) == "llm_unavailable"
    assert llm_client.get(f"{BASE}/{analysis}/suggestions").json()["usage"]["requested"] == 0


def test_correction_rules(llm_client: TestClient, analysis: str) -> None:
    url = f"{BASE}/{analysis}/spans"
    original = llm_client.get(url).json()["spans"][16]
    assert original["id"] == "s16"
    fixed = llm_client.patch(f"{url}/s16", json={"text": "Languages:  Python, SQL,  Scala, Go"})
    assert fixed.json()["text"] == "Languages: Python, SQL, Scala, Go"  # spacing normalized
    again = llm_client.patch(f"{url}/s16", json={"text": "Languages: Python, SQL, Go"})
    assert again.json()["text"] == "Languages: Python, SQL, Go"
    assert llm_client.get(url).json()["spans"][16]["text"] == "Languages: Python, SQL, Go"
    # Sending the original text removes the correction.
    reverted = llm_client.patch(f"{url}/s16", json={"text": original["original_text"]})
    assert reverted.json()["source"] == "extracted"
    assert llm_client.get(f"{BASE}/{analysis}/export/changes").json()["changes"] == []

    assert _error(llm_client.patch(f"{url}/s16", json={"text": "   "})) == "empty_text"
    assert llm_client.patch(f"{url}/s16", json={"text": ""}).status_code == 422
    assert llm_client.patch(f"{url}/s16", json={"text": "x" * 2001}).status_code == 422
    missing = llm_client.patch(f"{url}/s999", json={"text": "x"})
    assert missing.status_code == 404 and _error(missing) == "span_not_found"


def test_gap_questions_and_answers(llm_client: TestClient, analysis: str) -> None:
    url = f"{BASE}/{analysis}"
    questions = llm_client.get(f"{url}/gap-questions").json()["questions"]
    by_id = {q["requirement_id"]: q for q in questions}
    assert set(by_id) == {"r11", "r12"}
    assert by_id["r11"]["question"] == (
        "Have you used dbt? If yes, where, and what did you build with it?"
    )
    assert by_id["r11"]["answer"] is None

    answer = "Built 30 dbt models at a side project, no paid work yet."
    saved = llm_client.put(f"{url}/gap-answers/r11", json={"answer": answer})
    assert saved.status_code == 200
    assert saved.json()["answer"] == answer and saved.json()["answered_at"] is not None
    stored = {
        q["requirement_id"]: q for q in llm_client.get(f"{url}/gap-questions").json()["questions"]
    }
    assert stored["r11"]["answer"] == answer

    # Answers are never put into the resume.
    doc = Document(io.BytesIO(llm_client.get(f"{url}/export.docx").content))
    assert all("dbt models" not in p.text for p in doc.paragraphs)
    assert llm_client.get(f"{url}/export/changes").json()["changes"] == []

    changed = llm_client.put(f"{url}/gap-answers/r11", json={"answer": "Only in a course."})
    assert changed.json()["answer"] == "Only in a course."
    cleared = llm_client.put(f"{url}/gap-answers/r11", json={"answer": "  "})
    assert cleared.json()["answer"] is None
    no_question = llm_client.put(f"{url}/gap-answers/r6", json={"answer": "yes"})
    assert no_question.status_code == 404 and _error(no_question) == "no_gap_question"
    too_long = llm_client.put(f"{url}/gap-answers/r11", json={"answer": "x" * 4001})
    assert too_long.status_code == 422


@pytest.mark.parametrize(
    "call",
    [
        lambda c, a: c.get(f"{BASE}/{a}/suggestions"),
        lambda c, a: c.post(f"{BASE}/{a}/suggestions", json={}),
        lambda c, a: c.post(f"{BASE}/{a}/suggestions/abc/accept"),
        lambda c, a: c.post(f"{BASE}/{a}/suggestions/abc/reject"),
        lambda c, a: c.get(f"{BASE}/{a}/spans"),
        lambda c, a: c.patch(f"{BASE}/{a}/spans/s1", json={"text": "x"}),
        lambda c, a: c.get(f"{BASE}/{a}/gap-questions"),
        lambda c, a: c.put(f"{BASE}/{a}/gap-answers/r1", json={"answer": "x"}),
        lambda c, a: c.get(f"{BASE}/{a}/export.docx"),
        lambda c, a: c.get(f"{BASE}/{a}/export/changes"),
    ],
)
def test_unknown_analysis_is_404(
    llm_client: TestClient, call: Callable[[TestClient, str], Any]
) -> None:
    response = call(llm_client, "0" * 32)
    assert response.status_code == 404
    assert _error(response) == "not_found"


def test_unknown_suggestion_is_404(llm_client: TestClient, analysis: str) -> None:
    for action in ("accept", "reject"):
        response = llm_client.post(f"{BASE}/{analysis}/suggestions/nope/{action}")
        assert response.status_code == 404 and _error(response) == "suggestion_not_found"


def _rows(settings: Settings, analysis_id: str) -> int:
    db = Database(settings.database_url)
    try:
        for session in db.session():
            return AnalysisRepository(session).count_rows(analysis_id)
    finally:
        db.engine.dispose()
    raise AssertionError("no session")  # pragma: no cover


def _fill(client: TestClient, analysis_id: str) -> None:
    [s, *_] = _suggest(client, analysis_id, ["r6"]).json()["suggestions"]
    client.post(f"{BASE}/{analysis_id}/suggestions/{s['id']}/accept")
    client.patch(f"{BASE}/{analysis_id}/spans/s3", json={"text": "Fixed summary line."})
    client.put(f"{BASE}/{analysis_id}/gap-answers/r11", json={"answer": "No."})


def test_delete_removes_everything(
    tmp_path: Path, fake: FakeLLMClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        analysis_id = _create(client, data_engineer_markup, data_engineer_jd)["id"]
        _fill(client, analysis_id)
        # analysis, resume lines, 1 suggestion, 1 run, 1 correction, 1 answer
        assert _rows(settings, analysis_id) == 6
        assert client.delete(f"{BASE}/{analysis_id}").status_code == 204
        assert _rows(settings, analysis_id) == 0
        assert client.get(f"{BASE}/{analysis_id}/export.docx").status_code == 404


def test_expiry_removes_everything(
    tmp_path: Path, fake: FakeLLMClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        analysis_id = _create(client, data_engineer_markup, data_engineer_jd)["id"]
        _fill(client, analysis_id)
    db = Database(settings.database_url)
    try:
        for session in db.session():
            repo = AnalysisRepository(session)
            record = repo.get(analysis_id)
            assert record is not None
            record.expires_at = record.expires_at - timedelta(days=2)
            session.commit()
            assert repo.purge_expired() == 1
            assert repo.count_rows(analysis_id) == 0
    finally:
        db.engine.dispose()


def test_logs_hold_no_resume_text(
    tmp_path: Path,
    fake: FakeLLMClient,
    data_engineer_markup: str,
    data_engineer_jd: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(_settings(tmp_path, log_level="INFO"), llm_client=fake)
    logging.getLogger().addHandler(caplog.handler)
    caplog.handler.setLevel(logging.INFO)
    with TestClient(app) as client:
        analysis_id = _create(client, data_engineer_markup, data_engineer_jd)["id"]
        _fill(client, analysis_id)
        client.get(f"{BASE}/{analysis_id}/export.docx")
    messages = [r.getMessage() for r in caplog.records]
    assert "suggestions created" in messages and "export built" in messages
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in ("Jordan", "PySpark jobs", "data-quality", "Fixed summary line", "Northwind"):
        assert secret not in text


def test_stored_v0_2_reports_still_load() -> None:
    # A report saved by v0.2 has no job_parser and no free_text_skills.
    report = AnalysisReport.model_validate(
        {
            "pipeline_version": "0.2.0-exact",
            "job": {
                "title": None,
                "seniority": "unknown",
                "min_years": None,
                "requirements": [
                    {"id": "r0", "text": "Python", "priority": "required", "skills": ["Python"]}
                ],
            },
            "resume_sections": [],
            "coverage": {},
            "missing_required_skills": [],
            "listed_but_not_demonstrated": [],
            "matches": [],
        }
    )
    assert report.job_parser.name.value == "rules"
    assert report.job.requirements[0].free_text_skills == []
    assert FileType.PDF.value == "pdf"
