"""Upload scanning through the API, against a fake clamd."""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.builders import build_pdf
from tests.fake_clamd import EICAR, FakeClamd, closed_port, fake_clamd
from tests.support import authenticate, make_settings

PDF = "application/pdf"


def _app_client(database_url: str, port: int) -> TestClient:
    settings = make_settings(
        database_url,
        scanner="clamav",
        clamav_host="127.0.0.1",
        clamav_port=port,
        clamav_timeout_seconds=2,
        log_level="INFO",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def clamd() -> Iterator[FakeClamd]:
    with fake_clamd() as server:
        yield server


def _upload(client: TestClient, data: bytes, jd: str) -> Any:
    return client.post(
        "/api/v1/analyses",
        files={"resume": ("r.pdf", data, PDF)},
        data={"job_description": jd, "consent": "true"},
    )


def test_clean_upload_is_scanned_then_analyzed(
    database_url: str, clamd: FakeClamd, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    pdf = build_pdf(data_engineer_markup)
    with _app_client(database_url, clamd.port) as client:
        authenticate(client)
        response = _upload(client, pdf, data_engineer_jd)
        assert response.status_code == 201, response.text
        extract = client.post("/api/v1/extract", files={"resume": ("r.pdf", pdf, PDF)})
        assert extract.status_code == 200
        assert client.get("/readyz").json() == {"status": "ready"}
    assert clamd.received.streams == [pdf, pdf]
    assert b"zPING" in clamd.received.commands


def test_infected_upload_is_rejected_and_nothing_is_stored(
    database_url: str,
    clamd: FakeClamd,
    data_engineer_jd: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    infected = b"%PDF-1.7\n" + EICAR + b"\nJordan Example resume text\n%%EOF"
    with _app_client(database_url, clamd.port) as client:
        logging.getLogger().addHandler(caplog.handler)
        authenticate(client)
        response = _upload(client, infected, data_engineer_jd)
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "malware_detected"
        assert "virus scanner flagged this file" in error["message"]
        assert client.get("/api/v1/analyses").json()["analyses"] == []
        extract = client.post("/api/v1/extract", files={"resume": ("r.pdf", infected, PDF)})
        assert extract.status_code == 422
    [record, *_] = [r for r in caplog.records if r.getMessage() == "upload rejected by scanner"]
    assert record.signature == "Eicar-Test-Signature"  # type: ignore[attr-defined]
    assert record.user_id  # type: ignore[attr-defined]
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "EICAR-STANDARD" not in text and "Jordan Example" not in text


def test_scanner_errors_fail_closed(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    pdf = build_pdf(data_engineer_markup)
    with fake_clamd("error") as clamd, _app_client(database_url, clamd.port) as client:
        authenticate(client)
        response = _upload(client, pdf, data_engineer_jd)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "scanner_unavailable"
        assert response.headers["Retry-After"] == "30"
        assert client.get("/api/v1/analyses").json()["analyses"] == []


def test_unreachable_scanner_fails_closed(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    with _app_client(database_url, closed_port()) as client:
        authenticate(client)
        response = _upload(client, build_pdf(data_engineer_markup), data_engineer_jd)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "scanner_unavailable"
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["error"]["message"] == "The virus scanner is not reachable."
        # Only uploads stop: the rest of the API keeps working.
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/healthz").status_code == 200


def test_scanner_off_scans_nothing(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    assert client.app.state.scanner is None  # type: ignore[attr-defined]
    assert _upload(client, build_pdf(data_engineer_markup), data_engineer_jd).status_code == 201
