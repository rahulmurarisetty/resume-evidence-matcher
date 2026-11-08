"""Rate limits through the API: 429 with Retry-After, per account, per email and
per client address."""

from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from tests.builders import build_pdf
from tests.fakes import FakeLLMClient
from tests.integration.test_edits_api import rewrite_handler
from tests.support import EMAIL, PASSWORD, authenticate, bearer, login, make_settings, register

PDF = "application/pdf"


def _limited(response: Any) -> None:
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1
    assert f"{response.headers['Retry-After']} seconds" in response.json()["error"]["message"]


def test_login_attempts_per_email(database_url: str) -> None:
    settings = make_settings(database_url, rate_limit_auth="3/minute")
    with TestClient(create_app(settings)) as client:
        register(client)  # 1
        login(client)  # 2
        wrong = {"email": EMAIL, "password": "a wrong password"}
        assert client.post("/api/v1/auth/login", json=wrong).status_code == 401  # 3
        _limited(client.post("/api/v1/auth/login", json=wrong))
        # Even the right password waits: the email is out of attempts.
        _limited(client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}))
        # Another email still has its own, and the address has 5 times as many.
        register(client, "other@example.com")


def test_login_attempts_per_address(database_url: str) -> None:
    settings = make_settings(database_url, rate_limit_auth="10/minute", rate_limit_ip_multiplier=1)
    with TestClient(create_app(settings)) as client:
        for i in range(10):
            body = {"email": f"p{i}@example.com", "password": PASSWORD}
            assert client.post("/api/v1/auth/login", json=body).status_code == 401
        _limited(client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}))


def test_analyses_per_account(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    settings = make_settings(database_url, rate_limit_analyses="2/hour", max_upload_mb=5)
    pdf = build_pdf(data_engineer_markup)
    with TestClient(create_app(settings)) as client:
        authenticate(client)
        other = login_other(client)
        post = {
            "files": {"resume": ("r.pdf", pdf, PDF)},
            "data": {"job_description": data_engineer_jd, "consent": "true"},
        }
        assert client.post("/api/v1/analyses", **post).status_code == 201
        assert client.post("/api/v1/extract", files=post["files"]).status_code == 200
        _limited(client.post("/api/v1/analyses", **post))
        # Another account has its own allowance.
        assert client.post("/api/v1/analyses", headers=bearer(other), **post).status_code == 201


def login_other(client: TestClient) -> str:
    register(client, "other@example.com")
    return login(client, "other@example.com")


def test_suggestions_and_exports_per_account(
    database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    settings = make_settings(
        database_url,
        llm_enabled="on",
        max_upload_mb=5,
        rate_limit_suggestions="1/hour",
        rate_limit_exports="2/hour",
    )
    fake = FakeLLMClient(handler=rewrite_handler)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        authenticate(client)
        analysis_id = client.post(
            "/api/v1/analyses",
            files={"resume": ("r.pdf", build_pdf(data_engineer_markup), PDF)},
            data={"job_description": data_engineer_jd, "consent": "true", "llm_consent": "true"},
        ).json()["id"]
        url = f"/api/v1/analyses/{analysis_id}"
        assert (
            client.post(url + "/suggestions", json={"requirement_ids": ["r6"]}).status_code == 200
        )
        calls = len(fake.calls)
        _limited(client.post(url + "/suggestions", json={"requirement_ids": ["r2"]}))
        assert len(fake.calls) == calls  # refused before Claude was called
        assert client.get(url + "/suggestions").status_code == 200  # reading isn't limited

        assert client.get(url + "/export.docx").status_code == 200
        # v1.0: the match report shares the export allowance.
        assert client.get(url + "/report.html").status_code == 200
        _limited(client.get(url + "/export.docx"))
        _limited(client.get(url + "/report.html"))
        _limited(client.get(url + "/report.md"))
        assert client.get(url + "/export/changes").status_code == 200


def test_client_address_behind_a_trusted_proxy(database_url: str) -> None:
    settings = make_settings(
        database_url,
        rate_limit_auth="2/minute",
        rate_limit_ip_multiplier=1,
        trusted_proxies="10.0.0.0/8",
    )
    app = create_app(settings)
    # The test client connects from "testclient", which isn't a trusted proxy, so its
    # X-Forwarded-For is ignored and every request counts for the same address.
    with TestClient(app) as client:
        spoofed = [{"X-Forwarded-For": f"198.51.100.{i}"} for i in range(3)]
        for headers in spoofed[:2]:
            body = {"email": "a@example.com", "password": PASSWORD}
            client.post("/api/v1/auth/login", json=body, headers=headers)
        _limited(
            client.post(
                "/api/v1/auth/login",
                json={"email": "b@example.com", "password": PASSWORD},
                headers=spoofed[2],
            )
        )
    # From a trusted proxy, each forwarded address has its own bucket.
    with TestClient(app, client=("10.1.2.3", 50000)) as proxied:
        for i in range(4):
            response = proxied.post(
                "/api/v1/auth/login",
                json={"email": f"c{i}@example.com", "password": PASSWORD},
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
            )
            assert response.status_code == 401


def test_limits_can_be_turned_off(database_url: str) -> None:
    settings = make_settings(database_url, rate_limits_enabled=False, rate_limit_auth="1/hour")
    with TestClient(create_app(settings)) as client:
        assert client.app.state.limiter is None  # type: ignore[attr-defined]
        for _ in range(3):
            register(client)
