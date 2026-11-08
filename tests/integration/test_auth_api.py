"""Accounts and sessions through the API."""

import hashlib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.services import accounts
from app.storage.accounts import LOCAL_USER_ID
from app.storage.db import AuthSessionRecord, Database, UserRecord
from tests.builders import build_pdf
from tests.support import EMAIL, PASSWORD, authenticate, bearer, login, make_settings, register

AUTH = "/api/v1/auth"
PDF = "application/pdf"


def _rows(settings: Settings, model: type[Any]) -> list[Any]:
    db = Database(settings.database_url)
    try:
        for session in db.session():
            return list(session.scalars(select(model)))
    finally:
        db.engine.dispose()
    raise AssertionError("no session")  # pragma: no cover


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_register_login_me_logout(anon_client: TestClient, settings: Settings) -> None:
    response = anon_client.post(AUTH + "/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 202
    assert "Log in" in response.json()["message"]

    logged_in = anon_client.post(
        AUTH + "/login", json={"email": "  Person@Example.COM ", "password": PASSWORD}
    )
    assert logged_in.status_code == 200, logged_in.text
    body = logged_in.json()
    token = body["token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == EMAIL
    assert body["user"]["auth_mode"] == "required"
    assert len(token) >= 40

    me = anon_client.get(AUTH + "/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"] and me.json()["email"] == EMAIL

    assert anon_client.post(AUTH + "/logout", headers=bearer(token)).status_code == 204
    after = anon_client.get(AUTH + "/me", headers=bearer(token))
    assert after.status_code == 401 and _code(after) == "not_authenticated"
    assert after.headers["WWW-Authenticate"] == "Bearer"


def test_only_hashes_are_stored(anon_client: TestClient, settings: Settings) -> None:
    token = authenticate(anon_client)
    [user] = _rows(settings, UserRecord)
    assert user.email == EMAIL
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    [stored] = _rows(settings, AuthSessionRecord)
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored.token_hash


def test_each_login_is_its_own_session(anon_client: TestClient, settings: Settings) -> None:
    register(anon_client)
    first, second = login(anon_client), login(anon_client)
    assert first != second
    assert anon_client.post(AUTH + "/logout", headers=bearer(first)).status_code == 204
    assert anon_client.get(AUTH + "/me", headers=bearer(second)).status_code == 200
    assert len(_rows(settings, AuthSessionRecord)) == 1


def test_login_errors_dont_say_whether_the_email_exists(anon_client: TestClient) -> None:
    register(anon_client)
    wrong_password = anon_client.post(
        AUTH + "/login", json={"email": EMAIL, "password": "not the right password"}
    )
    unknown_email = anon_client.post(
        AUTH + "/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    not_an_email = anon_client.post(AUTH + "/login", json={"email": "x", "password": PASSWORD})
    for response in (wrong_password, unknown_email, not_an_email):
        assert response.status_code == 401
        assert response.json() == wrong_password.json()
    assert _code(wrong_password) == "invalid_credentials"


def test_registering_an_existing_email_answers_the_same(
    anon_client: TestClient, settings: Settings
) -> None:
    first = anon_client.post(AUTH + "/register", json={"email": EMAIL, "password": PASSWORD})
    again = anon_client.post(
        AUTH + "/register", json={"email": EMAIL.upper(), "password": "another long password"}
    )
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    assert len(_rows(settings, UserRecord)) == 1
    # The first password still works; the second never set anything.
    login(anon_client)
    failed = anon_client.post(
        AUTH + "/login", json={"email": EMAIL, "password": "another long password"}
    )
    assert failed.status_code == 401


def test_unknown_emails_cost_a_password_check(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[str] = []
    real = accounts.verify_password

    def counting(password_hash: str, password: str) -> bool:
        checks.append(password_hash)
        return real(password_hash, password)

    monkeypatch.setattr(accounts, "verify_password", counting)
    anon_client.post(AUTH + "/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert len(checks) == 1 and checks[0].startswith("$argon2id$")


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("not-an-email", PASSWORD, "invalid_email"),
        ("two words@example.com", PASSWORD, "invalid_email"),
        ("a@" + "b" * 260 + ".com", PASSWORD, "invalid_email"),
        (EMAIL, "elevenchars", "weak_password"),
        (EMAIL, "x" * 257, "weak_password"),
    ],
)
def test_register_checks(anon_client: TestClient, email: str, password: str, code: str) -> None:
    response = anon_client.post(AUTH + "/register", json={"email": email, "password": password})
    assert response.status_code == 422
    assert _code(response) == code
    if code == "weak_password":
        assert "12" in response.json()["error"]["message"] or "256" in response.text


def test_register_needs_both_fields(anon_client: TestClient) -> None:
    response = anon_client.post(AUTH + "/register", json={"email": EMAIL})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Invalid or missing fields: password"
    # The value is never echoed back.
    huge = anon_client.post(AUTH + "/login", json={"email": EMAIL, "password": "p" * 2000})
    assert huge.status_code == 422 and "ppp" not in huge.text


def test_expired_sessions_stop_working(anon_client: TestClient, settings: Settings) -> None:
    token = authenticate(anon_client)
    db = Database(settings.database_url)
    try:
        for session in db.session():
            record = session.scalars(select(AuthSessionRecord)).one()
            record.expires_at = record.expires_at - timedelta(hours=13)
            session.commit()
    finally:
        db.engine.dispose()
    response = anon_client.get(AUTH + "/me", headers=bearer(token))
    assert response.status_code == 401
    # The expired row is removed when it is seen.
    assert _rows(settings, AuthSessionRecord) == []


def test_session_lifetime_follows_the_setting(database_url: str) -> None:
    with TestClient(create_app(make_settings(database_url, session_ttl_hours=2))) as client:
        register(client)
        body = client.post(AUTH + "/login", json={"email": EMAIL, "password": PASSWORD}).json()
        user = client.get(AUTH + "/me", headers=bearer(body["token"])).json()
    from datetime import datetime

    lifetime = datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(
        user["created_at"]
    )
    assert timedelta(hours=1, minutes=59) < lifetime <= timedelta(hours=2, minutes=1)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer not-a-real-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "bearer"},
    ],
)
def test_bad_tokens_are_401(anon_client: TestClient, headers: dict[str, str]) -> None:
    response = anon_client.get(AUTH + "/me", headers=headers)
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


ANALYSIS = "/api/v1/analyses/" + "0" * 32
PROTECTED: list[Callable[[TestClient], Any]] = [
    lambda c: c.get("/api/v1/analyses"),
    lambda c: c.post("/api/v1/analyses", data={"job_description": "x" * 60}),
    lambda c: c.post("/api/v1/extract"),
    lambda c: c.get(ANALYSIS),
    lambda c: c.delete(ANALYSIS),
    lambda c: c.get(ANALYSIS + "/suggestions"),
    lambda c: c.post(ANALYSIS + "/suggestions"),
    lambda c: c.post(ANALYSIS + "/suggestions/x/accept"),
    lambda c: c.post(ANALYSIS + "/suggestions/x/reject"),
    lambda c: c.get(ANALYSIS + "/spans"),
    lambda c: c.patch(ANALYSIS + "/spans/s1", json={"text": "x"}),
    lambda c: c.get(ANALYSIS + "/gap-questions"),
    lambda c: c.put(ANALYSIS + "/gap-answers/r1", json={"answer": "x"}),
    lambda c: c.get(ANALYSIS + "/export.docx"),
    lambda c: c.get(ANALYSIS + "/export/changes"),
    lambda c: c.get(ANALYSIS + "/report.html"),
    lambda c: c.get(ANALYSIS + "/report.md"),
    lambda c: c.get("/api/v1/consent"),
    lambda c: c.post(AUTH + "/logout"),
    lambda c: c.get(AUTH + "/me"),
    lambda c: c.delete(AUTH + "/me"),
]


@pytest.mark.parametrize("call", PROTECTED)
def test_every_endpoint_needs_a_session(
    anon_client: TestClient, call: Callable[[TestClient], Any]
) -> None:
    response = call(anon_client)
    assert response.status_code == 401, response.text
    assert _code(response) == "not_authenticated"


def test_an_old_hash_is_upgraded_at_login(anon_client: TestClient, settings: Settings) -> None:
    register(anon_client)
    before = _rows(settings, UserRecord)[0].password_hash
    accounts.set_hasher(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    login(anon_client)
    after = _rows(settings, UserRecord)[0].password_hash
    assert before != after and "m=16,t=2" in after
    login(anon_client)  # still works, and isn't rehashed again
    assert _rows(settings, UserRecord)[0].password_hash == after


def test_auth_logs_have_ids_only(anon_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    logging.getLogger().addHandler(caplog.handler)
    caplog.handler.setLevel(logging.INFO)
    logging.getLogger("app").setLevel(logging.INFO)
    token = authenticate(anon_client)
    anon_client.post(AUTH + "/login", json={"email": EMAIL, "password": "wrong password!!"})
    anon_client.post(AUTH + "/logout")
    messages = [r.getMessage() for r in caplog.records]
    assert {"account created", "logged in", "login failed", "logged out"} <= set(messages)
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in (EMAIL, PASSWORD, "wrong password", token):
        assert secret not in text


# ---------------------------------------------------------------------------
# AUTH_MODE=disabled
# ---------------------------------------------------------------------------


def test_disabled_mode_uses_one_local_account(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    settings = make_settings(database_url, auth_mode="disabled", max_upload_mb=5)
    with TestClient(create_app(settings)) as client:
        me = client.get(AUTH + "/me").json()
        assert me["id"] == LOCAL_USER_ID and me["auth_mode"] == "disabled"
        created = client.post(
            "/api/v1/analyses",
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
            data={"job_description": data_engineer_jd, "consent": "true"},
        )
        assert created.status_code == 201
        assert client.get(f"/api/v1/analyses/{created.json()['id']}").status_code == 200
        for path in ("/register", "/login"):
            response = client.post(AUTH + path, json={"email": EMAIL, "password": PASSWORD})
            assert response.status_code == 409 and _code(response) == "auth_disabled"
        assert client.post(AUTH + "/logout").status_code == 409
        # Deleting "my data" deletes the local account's analyses; the account comes back.
        assert client.delete(AUTH + "/me").status_code == 204
        assert client.get("/api/v1/analyses").json()["analyses"] == []
        assert client.get(AUTH + "/me").json()["id"] == LOCAL_USER_ID


def test_nobody_can_log_in_as_the_local_account(database_url: str) -> None:
    with TestClient(create_app(make_settings(database_url, auth_mode="disabled"))) as client:
        client.get(AUTH + "/me")  # makes the local account
    with TestClient(create_app(make_settings(database_url))) as client:
        for password in ("!", "", PASSWORD):
            response = client.post(AUTH + "/login", json={"email": "local", "password": password})
            assert response.status_code == 401
