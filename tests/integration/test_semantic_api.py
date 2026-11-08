"""The API with matching by meaning: fakes injected at app creation, and how startup
handles each SEMANTIC_MATCHING setting. No real model is ever loaded."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.config import Settings
from app.main import create_app, start_semantic
from app.models import AnalysisReport, MatchingMode
from tests.builders import build_pdf
from tests.fakes import FakeEncoder, FakeReranker
from tests.support import authenticate, make_settings

PDF = "application/pdf"


def _settings(database_url: str, mode: str) -> Settings:
    return make_settings(database_url, semantic_matching=mode, max_upload_mb=5)


def test_report_includes_profile(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    response = client.post(
        "/api/v1/analyses",
        files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
        data={"job_description": data_engineer_jd, "consent": "true"},
    )
    report = response.json()["report"]
    profile = report["profile"]
    assert [r["title"] for r in profile["roles"]] == ["Senior Data Engineer", "Data Engineer"]
    assert profile["roles"][0]["is_current"] is True
    assert profile["total_years"] >= 7.5  # grows with the real date
    assert profile["education"][0]["school"] == "Example State University"
    assert profile["metric_bullets"] == ["s6", "s7", "s8", "s13"]
    # Semantic matching is off in the test settings.
    assert report["matching_mode"] == "exact"
    assert any("Matching by meaning is off" in w for w in report["warnings"])
    assert all(m["related_evidence"] == [] for m in report["matches"])


def test_injected_fakes_are_used(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    encoder, reranker = FakeEncoder(), FakeReranker()
    app = create_app(_settings(database_url, "off"), encoder=encoder, reranker=reranker)
    with TestClient(app) as client:
        authenticate(client)
        response = client.post(
            "/api/v1/analyses",
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
            data={"job_description": data_engineer_jd, "consent": "true"},
        )
        assert response.status_code == 201, response.text
        stored = client.get(f"/api/v1/analyses/{response.json()['id']}").json()
    report = response.json()["report"]
    assert stored["report"] == report
    assert report["pipeline_version"] == "1.0.0-semantic"
    assert report["matching_mode"] == "semantic"
    assert report["coverage"]["context"]["adjacent"] == 2
    assert report["coverage"]["required"]["direct"] == 5
    mentor = next(m for m in report["matches"] if m["requirement"]["text"].startswith("Mentor"))
    assert mentor["status"] == "adjacent"
    assert mentor["related_evidence"][0]["text"].startswith("Reviewed pull requests")
    assert encoder.calls == 2  # resume lines and requirements, once each
    assert len(reranker.queries) == len(report["matches"])


def test_startup_off_and_auto_without_the_library(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "sentence_transformers_available", lambda: False)
    assert start_semantic(_settings(database_url, "off")) == (None, None)
    assert start_semantic(_settings(database_url, "auto")) == (None, None)


def test_startup_on_without_the_library_fails(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "sentence_transformers_available", lambda: False)
    with (
        pytest.raises(RuntimeError, match="ml extra"),
        TestClient(create_app(_settings(database_url, "on"))),
    ):
        pass  # pragma: no cover


def test_startup_loads_models_once(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    data_engineer_markup: str,
    data_engineer_jd: str,
) -> None:
    loaded: list[tuple[str, str]] = []

    def fake_load(embedding: str, rerank: str) -> tuple[FakeEncoder, FakeReranker]:
        loaded.append((embedding, rerank))
        return FakeEncoder(), FakeReranker()

    monkeypatch.setattr(main, "sentence_transformers_available", lambda: True)
    monkeypatch.setattr(main, "load_models", fake_load)
    settings = _settings(database_url, "auto")
    with TestClient(create_app(settings)) as client:
        authenticate(client)
        for _ in range(2):
            report = client.post(
                "/api/v1/analyses",
                files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
                data={"job_description": data_engineer_jd, "consent": "true"},
            ).json()["report"]
            assert report["matching_mode"] == "semantic"
    assert loaded == [(settings.embedding_model, settings.rerank_model)]


def test_auto_falls_back_when_models_fail(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(embedding: str, rerank: str) -> None:
        raise OSError("no network")

    monkeypatch.setattr(main, "sentence_transformers_available", lambda: True)
    monkeypatch.setattr(main, "load_models", broken)
    assert start_semantic(_settings(database_url, "auto")) == (None, None)
    with pytest.raises(OSError):
        start_semantic(_settings(database_url, "on"))


def test_semantic_setting_values(database_url: str) -> None:
    assert _settings(database_url, " OFF ").semantic_matching == "off"
    with pytest.raises(ValidationError):
        _settings(database_url, "sometimes")


def test_reports_stored_by_v0_1_still_load(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    # Reports live for up to 24 hours, so an upgrade meets reports without the v0.2 fields.
    report = client.post(
        "/api/v1/analyses",
        files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
        data={"job_description": data_engineer_jd, "consent": "true"},
    ).json()["report"]
    for key in ("profile", "matching_mode"):
        del report[key]
    for bucket in report["coverage"].values():
        del bucket["adjacent"]
    for match in report["matches"]:
        del match["related_evidence"], match["years_found"]
    old = AnalysisReport.model_validate(report)
    assert old.profile.roles == []
    assert old.matching_mode is MatchingMode.EXACT
