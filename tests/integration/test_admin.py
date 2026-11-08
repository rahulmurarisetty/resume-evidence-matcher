"""`python -m app.admin`: reset a password or delete an account by email."""

import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import admin
from app.config import Settings
from app.main import create_app
from tests.builders import build_pdf
from tests.support import EMAIL, PASSWORD, authenticate, bearer, make_settings

NEW_PASSWORD = "a brand new long password"
PDF = "application/pdf"


@pytest.fixture
def app_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(settings.database_url, max_upload_mb=5))) as client:
        yield client


def _run(settings: Settings, *argv: str, stdin: str = "", **prompts: object) -> tuple[int, str]:
    out = io.StringIO()
    code = admin.main(
        list(argv),
        settings=settings,
        stdin=io.StringIO(stdin),
        stdout=out,
        **prompts,  # type: ignore[arg-type]
    )
    return code, out.getvalue()


def _login(client: TestClient, password: str) -> int:
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})
    return response.status_code


def test_reset_password_ends_every_session(app_client: TestClient, settings: Settings) -> None:
    token = authenticate(app_client)
    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    code, out = _run(
        settings,
        "reset-password",
        " Person@Example.com ",
        prompt_password=lambda _: next(answers),
    )
    assert code == 0, out
    assert "1 session(s)" in out
    assert app_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert _login(app_client, PASSWORD) == 401
    assert _login(app_client, NEW_PASSWORD) == 200


def test_reset_password_from_stdin(app_client: TestClient, settings: Settings) -> None:
    authenticate(app_client)
    code, _ = _run(settings, "reset-password", EMAIL, "--password-stdin", stdin=NEW_PASSWORD + "\n")
    assert code == 0
    assert _login(app_client, NEW_PASSWORD) == 200


@pytest.mark.parametrize(
    ("argv", "stdin", "answers", "message"),
    [
        (["--password-stdin"], "too short\n", [], "at least 12 characters"),
        ([], "", [NEW_PASSWORD, NEW_PASSWORD + "!"], "differ"),
    ],
)
def test_reset_password_refusals(
    app_client: TestClient,
    settings: Settings,
    argv: list[str],
    stdin: str,
    answers: list[str],
    message: str,
) -> None:
    authenticate(app_client)
    replies = iter(answers)
    code, out = _run(
        settings,
        "reset-password",
        EMAIL,
        *argv,
        stdin=stdin,
        prompt_password=lambda _: next(replies),
    )
    assert code == 2 and message in out and "Nothing changed" in out
    assert _login(app_client, PASSWORD) == 200


def test_unknown_email(app_client: TestClient, settings: Settings) -> None:
    code, out = _run(settings, "delete-user", "nobody@example.com", "--yes")
    assert code == 1 and "No account" in out


def test_delete_user_asks_first(
    app_client: TestClient,
    settings: Settings,
    data_engineer_markup: str,
    data_engineer_jd: str,
) -> None:
    token = authenticate(app_client)
    app_client.post(
        "/api/v1/analyses",
        files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
        data={"job_description": data_engineer_jd, "consent": "true"},
    )
    code, out = _run(settings, "delete-user", EMAIL, prompt=lambda _: "someone@example.com")
    assert code == 2 and "Nothing was deleted" in out
    assert app_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200

    code, out = _run(settings, "delete-user", EMAIL, prompt=lambda _: "PERSON@example.com")
    assert code == 0 and "1 analysis(es)" in out
    assert app_client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert _login(app_client, PASSWORD) == 401


def test_delete_user_without_asking(app_client: TestClient, settings: Settings) -> None:
    authenticate(app_client)
    code, out = _run(settings, "delete-user", EMAIL, "--yes")
    assert code == 0 and "0 analysis(es)" in out


def test_refuses_an_unmigrated_database(empty_database_url: str) -> None:
    code, out = _run(make_settings(empty_database_url), "delete-user", EMAIL, "--yes")
    assert code == 2 and "migrations are pending" in out
