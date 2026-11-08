import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import FileType
from app.storage.db import Database
from app.storage.repository import AnalysisRepository
from tests.builders import build_docx, build_pdf

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _post(client: TestClient, data: bytes, jd: str, name: str = "resume.pdf", mime: str = PDF):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/analyses",
        files={"resume": (name, data, mime)},
        data={"job_description": jd},
    )


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_create_get_delete(
    client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    created = _post(client, build_pdf(data_engineer_markup), data_engineer_jd)
    assert created.status_code == 201, created.text
    body = created.json()
    analysis_id = body["id"]
    assert created.headers["Location"] == f"/api/v1/analyses/{analysis_id}"
    assert body["report"]["coverage"]["required"]["direct"] == 4
    assert body["report"]["pipeline_version"].endswith("exact")

    fetched = client.get(f"/api/v1/analyses/{analysis_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204
    assert client.get(f"/api/v1/analyses/{analysis_id}").status_code == 404
    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 404


def test_docx_upload(client: TestClient, dotnet_markup: str, dotnet_jd: str) -> None:
    response = _post(client, build_docx(dotnet_markup), dotnet_jd, "resume.docx", DOCX)
    assert response.status_code == 201, response.text
    assert response.json()["report"]["coverage"]["required"]["direct"] == 4


def test_file_type_comes_from_bytes_not_name(client: TestClient, data_engineer_jd: str) -> None:
    response = _post(client, b"plain text " * 100, data_engineer_jd, "resume.pdf", PDF)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"


def test_file_over_limit(client: TestClient, data_engineer_jd: str) -> None:
    # The test settings allow 1 MB.
    response = _post(client, b"%PDF-1.7\n" + b"0" * (1024 * 1024 + 10), data_engineer_jd)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_body_far_over_limit_is_rejected_before_parsing(
    client: TestClient, data_engineer_jd: str
) -> None:
    response = _post(client, b"%PDF-1.7\n" + b"0" * (3 * 1024 * 1024), data_engineer_jd)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_short_and_missing_job_description(client: TestClient, data_engineer_markup: str) -> None:
    pdf = build_pdf(data_engineer_markup)
    assert _post(client, pdf, "python").json()["error"]["code"] == "job_description_too_short"
    missing = client.post("/api/v1/analyses", files={"resume": ("r.pdf", pdf, PDF)})
    assert missing.status_code == 422
    assert "job_description" in missing.json()["error"]["message"]


def test_extract_endpoint_returns_spans(client: TestClient, data_engineer_markup: str) -> None:
    response = client.post(
        "/api/v1/extract", files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)}
    )
    assert response.status_code == 200
    spans = response.json()["resume"]["spans"]
    assert spans[0]["text"] == "Jordan Example"
    assert all({"id", "text", "section", "page"} <= set(s) for s in spans)


def test_request_id_is_echoed_or_created(client: TestClient) -> None:
    assert (
        client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
        == "abc-123"
    )
    generated = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert generated.headers["X-Request-ID"] != "bad id with spaces"


def test_expired_analyses_are_hidden_and_purged(
    client: TestClient, settings: Settings, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    body = _post(client, build_pdf(data_engineer_markup), data_engineer_jd).json()
    report = client.get(f"/api/v1/analyses/{body['id']}").json()["report"]

    from app.models import AnalysisReport

    db = Database(settings.database_url)
    try:
        for session in db.session():
            repo = AnalysisRepository(session)
            old = repo.create(
                AnalysisReport.model_validate(report),
                FileType.PDF,
                "0" * 64,
                timedelta(seconds=-1),
            )
            assert repo.get(old.id) is None
            assert repo.purge_expired() == 1
            assert repo.get(body["id"]) is not None
    finally:
        db.engine.dispose()


def test_uploads_under_the_limit_stay_in_memory(
    tmp_path: Path, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    # Starlette writes uploads over 1 MB to a temp file by default. The app raises that
    # threshold to its own upload limit so resumes never touch the disk.
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=f"sqlite:///{tmp_path / 'spool.db'}",
        max_upload_mb=5,
        log_level="WARNING",
    )
    padded = build_pdf(data_engineer_markup) + b"%" + b"0" * (3 * 1024 * 1024)
    rollover = tempfile.SpooledTemporaryFile.rollover
    with (
        mock.patch.object(
            tempfile.SpooledTemporaryFile, "rollover", autospec=True, side_effect=rollover
        ) as spilled,
        TestClient(create_app(settings)) as client,
    ):
        response = _post(client, padded, data_engineer_jd)
    assert response.status_code == 201, response.text
    assert not spilled.called
