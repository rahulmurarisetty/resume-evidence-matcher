"""Security headers on every response, the docs page's own policy, CORS, HSTS in
production, and the answer to an unexpected error."""

import base64
import hashlib
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.api.headers import JSON_CSP
from app.config import Settings
from app.logging_setup import HIDDEN, JsonFormatter
from app.main import create_app
from tests.support import make_settings

COMMON = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _common(response: object) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    for name, value in COMMON.items():
        assert headers[name] == value, name
    assert "X-Request-ID" in headers


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/healthz", 200),
        ("GET", "/api/v1/auth/me", 401),
        ("GET", "/api/v1/analyses/" + "0" * 32, 401),
        ("GET", "/no-such-page", 404),
        ("POST", "/api/v1/auth/login", 422),
        ("GET", "/openapi.json", 200),
    ],
)
def test_every_response_has_the_headers(
    anon_client: TestClient, method: str, path: str, status: int
) -> None:
    response = anon_client.request(method, path)
    assert response.status_code == status
    _common(response)
    assert response.headers["Content-Security-Policy"] == JSON_CSP
    assert "Strict-Transport-Security" not in response.headers  # local: plain HTTP
    if path.startswith("/api/"):
        assert response.headers["Cache-Control"] == "no-store"


def test_reports_are_never_cached(client: TestClient) -> None:
    assert client.get("/api/v1/analyses").headers["Cache-Control"] == "no-store"


def test_too_large_requests_have_the_headers(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyses", content=b"x", headers={"Content-Length": str(50 * 1024 * 1024)}
    )
    assert response.status_code == 413
    _common(response)


def test_docs_page_policy_allows_only_its_own_script(anon_client: TestClient) -> None:
    response = anon_client.get("/docs")
    assert response.status_code == 200
    _common(response)
    csp = response.headers["Content-Security-Policy"]
    script_src = next(p for p in csp.split("; ") if p.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "frame-ancestors 'none'" in csp and "default-src 'none'" in csp
    [inline] = re.findall(r"<script>(.*?)</script>", response.text, re.DOTALL)
    digest = base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in script_src
    assert anon_client.get("/redoc").status_code == 404


def test_hsts_in_production(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Production refuses SQLite; this test only looks at the headers.
    monkeypatch.setattr(Settings, "production_problems", lambda self: [])
    settings = make_settings(database_url, app_env="production", db_auto_migrate=True)
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_cors_comes_from_the_settings_only(database_url: str) -> None:
    settings = make_settings(database_url, cors_origins="https://ui.example.com")
    with TestClient(create_app(settings)) as client:
        preflight = {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        }
        allowed = client.options(
            "/api/v1/analyses", headers={"Origin": "https://ui.example.com", **preflight}
        )
        assert allowed.headers["Access-Control-Allow-Origin"] == "https://ui.example.com"
        assert "authorization" in allowed.headers["Access-Control-Allow-Headers"].lower()
        _common(allowed)
        other = client.options(
            "/api/v1/analyses", headers={"Origin": "https://evil.example.com", **preflight}
        )
        assert "Access-Control-Allow-Origin" not in other.headers
        simple = client.get("/healthz", headers={"Origin": "https://evil.example.com"})
        assert "Access-Control-Allow-Origin" not in simple.headers


def test_an_unexpected_error_is_answered_without_its_message(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Built here so the traceback's source line for the raise doesn't quote it.
    secret = "Jordan Example, " + "person" + "@example.com"

    def boom() -> None:
        raise ValueError(secret)

    client.app.add_api_route("/boom", boom)  # type: ignore[attr-defined]
    logging.getLogger().addHandler(caplog.handler)
    response = client.get("/boom", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "req-123" in response.json()["error"]["message"]
    assert "Jordan" not in response.text
    _common(response)
    [record] = [r for r in caplog.records if r.getMessage() == "unhandled error"]
    formatted = JsonFormatter().format(record)
    assert "Jordan" not in formatted and "person@example.com" not in formatted
    assert HIDDEN in formatted and "ValueError" in formatted


def test_request_logs_name_the_route_not_the_url(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    logging.getLogger().addHandler(caplog.handler)
    logging.getLogger("app").setLevel(logging.INFO)
    client.get("/api/v1/analyses/" + "0" * 32)
    client.get("/api/v1/person@example.com")
    paths = [getattr(r, "path", None) for r in caplog.records if r.getMessage() == "request"]
    assert paths == ["/api/v1/analyses/{analysis_id}", "unmatched"]
