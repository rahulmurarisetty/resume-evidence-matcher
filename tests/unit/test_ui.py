"""The Streamlit screen's helpers, run against the real API. Streamlit itself is
optional: the screen tests skip when it isn't installed. They drive the screen
against the API running on a local port, because the screen calls it over HTTP."""

import importlib.util
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.builders import build_docx, build_pdf
from tests.fakes import FakeLLMClient
from tests.support import EMAIL, PASSWORD, authenticate, bearer, make_settings, register

UI_APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"


@pytest.fixture(scope="module")
def ui() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ui_app", UI_APP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_helpers_against_the_api(
    ui: ModuleType, client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    pdf = build_pdf(data_engineer_markup)
    analysis = ui.create_analysis(client, "resume.pdf", pdf, data_engineer_jd, consent=True)
    report = analysis["report"]

    rows = ui.coverage_rows(report)
    assert [row["Requirements"] for row in rows] == ["Required", "Preferred", "Job duties"]
    assert rows[0]["Total"] == 6
    assert rows[0]["Proven"] == 5

    groups = ui.matches_by_priority(report)
    assert [label for label, _ in groups] == ["Required", "Preferred", "Job duties"]
    git = next(m for m in report["matches"] if m["requirement"]["text"].startswith("Comfortable"))
    assert ui.exact_evidence(git) == [
        ("Cloud and tools: AWS, Git, CI/CD, Docker, Kubernetes", "skills, page 1")
    ]

    extracted = ui.extract_text(client, "resume.pdf", pdf)
    assert extracted["resume"]["spans"][0]["text"] == "Jordan Example"

    ui.delete_analysis(client, analysis["id"])
    with pytest.raises(ui.ApiError, match="No analysis with that id"):
        ui.delete_analysis(client, analysis["id"])


def test_docx_upload_uses_the_word_mime_type(
    ui: ModuleType, client: TestClient, dotnet_markup: str, dotnet_jd: str
) -> None:
    analysis = ui.create_analysis(
        client, "Resume.DOCX", build_docx(dotnet_markup), dotnet_jd, consent=True
    )
    assert analysis["report"]["coverage"]["required"]["total"] == 6
    assert ui.mime_type("cv.pdf") == "application/pdf"
    assert ui.mime_type("cv") == "application/octet-stream"


def test_api_errors_carry_the_message(ui: ModuleType, client: TestClient) -> None:
    with pytest.raises(ui.ApiError, match="Paste the full job description"):
        ui.create_analysis(client, "r.pdf", b"%PDF-1.7 tiny", "too short", consent=True)
    # v1.0: without the consent box nothing is read.
    with pytest.raises(ui.ApiError, match="Tick the box") as error:
        ui.create_analysis(client, "r.pdf", b"%PDF-1.7 tiny", "x" * 80, consent=False)
    assert error.value.code == "consent_required"
    assert ui.error_place(error.value.code) == "consent"
    with pytest.raises(ui.ApiError, match="status 404"):
        ui._check(client.get("/no-such-page"))


def test_text_helpers(ui: ModuleType) -> None:
    assert ui.escape_markdown("Saved $1.2M (3x) *fast*") == r"Saved \$1\.2M \(3x\) \*fast\*"
    assert ui.where("experience", 2) == "experience, page 2"
    assert ui.where("not_assessed", None) == "not assessed"
    assert set(ui.STATUS_LABELS) == {"direct", "partial", "adjacent", "gap", "not_assessed"}


def test_screen_renders_without_errors() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    screen = AppTest.from_file(str(UI_APP)).run()
    assert not screen.exception
    assert screen.title[0].value == "Resume evidence matcher"


def test_edit_helpers_against_the_api(
    ui: ModuleType, database_url: str, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    from app.main import create_app
    from tests.integration.test_edits_api import rewrite_handler

    settings = make_settings(database_url, llm_enabled="on")
    fake = FakeLLMClient(handler=rewrite_handler)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        authenticate(client)
        analysis = ui.create_analysis(
            client,
            "resume.pdf",
            build_pdf(data_engineer_markup),
            data_engineer_jd,
            consent=True,
            llm_consent=True,
        )
        analysis_id = analysis["id"]
        matches = {m["requirement"]["id"]: m for m in analysis["report"]["matches"]}
        assert ui.can_suggest(matches["r6"])
        assert not ui.can_suggest(matches["r5"])  # years only
        assert not ui.can_suggest(matches["r11"])  # a gap

        edits = ui.load_edits(client, analysis_id)
        assert edits["suggestions"] == [] and edits["changes"] == []
        assert edits["lines_stored"] is True
        assert set(edits["questions"]) == {"r11", "r12"}
        assert edits["spans"][0]["text"] == "Jordan Example"

        batch = ui.request_suggestions(client, analysis_id, ["r6"])
        assert ui._batch_note(batch) == (
            "1 new suggestion. 1 more were thrown away because they added facts."
        )
        [suggestion] = ui.suggestions_for(ui.list_suggestions(client, analysis_id), "r6")
        assert ui.decide_suggestion(client, analysis_id, suggestion["id"], True)["status"] == (
            "accepted"
        )
        ui.correct_line(client, analysis_id, "s3", "A corrected summary line.")
        ui.save_gap_answer(client, analysis_id, "r11", "Only in a course.")

        edits = ui.load_edits(client, analysis_id)
        assert edits["questions"]["r11"]["answer"] == "Only in a course."
        assert ui.change_rows(edits["changes"]) == [
            {
                "Change": "Your correction",
                "Before": edits["spans"][3]["original_text"],
                "After": "A corrected summary line.",
            },
            {
                "Change": "Accepted rewrite",
                "Before": suggestion["original"],
                "After": suggestion["text"],
            },
        ]
        data = ui.download_export(client, analysis_id)
        assert data.startswith(b"PK")
        with pytest.raises(ui.ApiError) as error:
            ui.decide_suggestion(client, analysis_id, "missing", False)
        assert error.value.code == "suggestion_not_found"


def test_suggestions_off_message(
    ui: ModuleType, client: TestClient, dotnet_markup: str, dotnet_jd: str
) -> None:
    analysis = ui.create_analysis(
        client, "r.docx", build_docx(dotnet_markup), dotnet_jd, consent=True
    )
    with pytest.raises(ui.ApiError, match="need Claude") as error:
        ui.request_suggestions(client, analysis["id"])
    assert error.value.code == "llm_disabled"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_account_helpers_against_the_api(ui: ModuleType, anon_client: TestClient) -> None:
    assert ui.current_user(anon_client) is None
    message = ui.register(anon_client, EMAIL, PASSWORD)
    assert "Log in" in message
    with pytest.raises(ui.ApiError, match="at least 12") as error:
        ui.register(anon_client, "other@example.com", "short")
    assert error.value.code == "weak_password"
    with pytest.raises(ui.ApiError, match="email or password is wrong"):
        ui.login(anon_client, EMAIL, "not the password")

    result = ui.login(anon_client, EMAIL, PASSWORD)
    anon_client.headers.update(bearer(result["token"]))
    assert ui.current_user(anon_client)["email"] == EMAIL
    ui.logout(anon_client)
    assert ui.current_user(anon_client) is None

    anon_client.headers.update(bearer(ui.login(anon_client, EMAIL, PASSWORD)["token"]))
    ui.delete_account(anon_client)
    assert ui.current_user(anon_client) is None
    with pytest.raises(ui.ApiError, match="email or password is wrong"):
        ui.login(anon_client, EMAIL, PASSWORD)


def test_api_client_headers(ui: ModuleType) -> None:
    with ui.api_client("tok", "203.0.113.7") as client:
        assert client.headers["Authorization"] == "Bearer tok"
        assert client.headers["X-Forwarded-For"] == "203.0.113.7"
    with ui.api_client() as client:
        assert "Authorization" not in client.headers and "X-Forwarded-For" not in client.headers


@pytest.mark.parametrize(
    ("incoming", "peer", "expected"),
    [
        (None, None, None),
        (None, "10.0.0.4", "10.0.0.4"),
        ("203.0.113.7", "10.0.0.4", "203.0.113.7, 10.0.0.4"),
        (" 1.1.1.1 ,, 203.0.113.7 ", None, "1.1.1.1, 203.0.113.7"),
    ],
)
def test_forwarded_for(
    ui: ModuleType, incoming: str | None, peer: str | None, expected: Any
) -> None:
    assert ui.forwarded_for(incoming, peer) == expected


def test_forwarded_for_is_bounded(ui: ModuleType) -> None:
    value = ui.forwarded_for(", ".join(["198.51.100.1"] * 500), "10.0.0.4")
    assert len(value) <= 2000 and value.endswith("10.0.0.4") and not value.startswith(",")


def test_export_key_follows_the_changes(ui: ModuleType) -> None:
    change = {"kind": "correction", "before": "a", "after": "b"}
    assert ui.export_key("x", []) != ui.export_key("x", [change])
    assert ui.export_key("x", [change]) == ui.export_key("x", [dict(change)])


# ---------------------------------------------------------------------------
# The screen, against the API on a local port
# ---------------------------------------------------------------------------


@pytest.fixture
def live_api(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The API served by uvicorn on a free local port, with API_URL pointing at it."""
    pytest.importorskip("streamlit")
    import uvicorn

    from app.main import create_app

    def serve(**values: Any) -> str:
        app = create_app(make_settings(database_url, **values))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        config = uvicorn.Config(app, log_config=None, ws="none", loop="asyncio", http="h11")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "the API didn't start"
            time.sleep(0.02)
        servers.append((server, thread, sock))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        monkeypatch.setenv("API_URL", url)
        return url

    servers: list[tuple[Any, threading.Thread, socket.socket]] = []
    yield serve  # type: ignore[misc]
    for server, thread, sock in servers:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def _screen() -> Any:
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(UI_APP), default_timeout=30).run()


def _button(screen: Any, label: str) -> Any:
    return next(b for b in screen.button if b.label == label)


def _texts(screen: Any) -> str:
    parts = [
        e.value for kind in ("error", "info", "warning", "success") for e in getattr(screen, kind)
    ]
    parts += [m.value for m in screen.markdown]
    return " ".join(str(p) for p in parts)


def test_screen_register_logout_and_delete_account(live_api: Any) -> None:
    url = live_api()
    screen = _screen()
    assert not screen.exception
    assert [t.label for t in screen.tabs] == ["Log in", "Create account"]
    assert not any(b.label == "Check my resume" for b in screen.button)

    screen.text_input(key="register-email").input(EMAIL)
    screen.text_input(key="register-password").input(PASSWORD)
    screen.text_input(key="register-again").input(PASSWORD + "x")
    _button(screen, "Create account").click().run()
    assert "The two passwords differ." in _texts(screen)

    screen.text_input(key="register-again").input(PASSWORD)
    _button(screen, "Create account").click().run()
    assert not screen.exception
    assert screen.session_state["token"] and screen.session_state["user"]["email"] == EMAIL
    assert any(b.label == "Check my resume" for b in screen.button)
    assert f"Logged in as {EMAIL}" in _texts(screen)

    screen.button(key="logout").click().run()
    assert "token" not in screen.session_state
    assert "Logged out." in _texts(screen)

    screen.text_input(key="login-email").input(EMAIL)
    screen.text_input(key="login-password").input("wrong password!")
    _button(screen, "Log in").click().run()
    assert "The email or password is wrong." in _texts(screen)
    screen.text_input(key="login-password").input(PASSWORD)
    _button(screen, "Log in").click().run()
    assert screen.session_state["user"]["email"] == EMAIL

    screen.button(key="delete-account").click().run()
    assert "can't be undone" in _texts(screen)
    screen.button(key="delete-cancel").click().run()
    assert "confirm_delete" not in screen.session_state
    screen.button(key="delete-account").click().run()
    screen.button(key="delete-confirm").click().run()
    assert not screen.exception
    assert "token" not in screen.session_state
    assert "Your account and all of its data were deleted." in _texts(screen)
    with httpx.Client(base_url=url) as client:
        response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 401


def test_screen_forgets_an_ended_session(live_api: Any) -> None:
    url = live_api()
    screen = _screen()
    with httpx.Client(base_url=url) as client:
        register(client)
    screen.text_input(key="login-email").input(EMAIL)
    screen.text_input(key="login-password").input(PASSWORD)
    _button(screen, "Log in").click().run()
    token = screen.session_state["token"]
    with httpx.Client(base_url=url) as client:
        client.post("/api/v1/auth/logout", headers=bearer(token))
    # The next action finds the token refused and goes back to the login screen.
    _button(screen, "Delete my account and data").click().run()
    _button(screen, "Yes, delete everything").click().run()
    assert "token" not in screen.session_state
    assert "Your session ended. Log in again." in _texts(screen)


def test_screen_without_accounts(live_api: Any) -> None:
    live_api(auth_mode="disabled")
    screen = _screen()
    assert not screen.exception
    assert not screen.tabs
    assert any(b.label == "Check my resume" for b in screen.button)
    assert "Accounts are off on this server" in " ".join(c.value for c in screen.caption)


# ---------------------------------------------------------------------------
# v1.0: consent, the match report and errors next to their inputs
# ---------------------------------------------------------------------------


def test_status_and_error_place_helpers(ui: ModuleType) -> None:
    assert ui.status_text("direct") == "Status: Proven"
    assert ui.status_text("not_assessed") == "Status: Check it yourself"
    assert ui.status_text("new_kind") == "Status: new kind"
    assert ui.error_place("job_description_too_short") == "job"
    assert ui.error_place("consent_required") == "consent"
    assert ui.error_place("unsupported_type") == "file"
    assert ui.error_place("malware_detected") == "file"
    assert ui.error_place("rate_limited") == "form"
    assert ui.error_place("") == "form"


def test_consent_and_report_helpers_against_the_api(
    ui: ModuleType, client: TestClient, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    notice = ui.consent_notice(client)
    assert notice["version"] == "consent_v1" and notice["llm_available"] is False
    analysis = ui.create_analysis(
        client, "resume.pdf", build_pdf(data_engineer_markup), data_engineer_jd, consent=True
    )
    assert analysis["consent"]["version"] == "consent_v1"
    edits = ui.load_edits(client, analysis["id"])
    assert edits["metric_questions"] and all(
        q["kind"] == "metric" for q in edits["metric_questions"]
    )
    assert all(q["kind"] == "gap" for q in edits["questions"].values())
    assert ui.download_report(client, analysis["id"], "html").startswith(b"<!DOCTYPE html>")
    assert ui.download_report(client, analysis["id"], "md").startswith(b"# Match report")


def test_screen_asks_for_consent_and_writes_errors_next_to_inputs(live_api: Any) -> None:
    url = live_api()
    with httpx.Client(base_url=url) as client:
        register(client)
    screen = _screen()
    screen.text_input(key="login-email").input(EMAIL)
    screen.text_input(key="login-password").input(PASSWORD)
    _button(screen, "Log in").click().run()
    assert not screen.exception
    assert [h.value for h in screen.header] == ["Check your resume against a job"]
    notice = screen.session_state["consent_notice"]
    # One box: Claude is off on this server, so there is no second one.
    assert [c.label for c in screen.checkbox] == [notice["checkbox"]]
    shown = _texts(screen)
    assert "Before you upload:" in shown and "Only your account can see your analyses" in shown

    _button(screen, "Check my resume").click().run()
    errors = [e.value for e in screen.error]
    assert errors == [
        "Tick the box above to agree before the resume is read.",
        "Choose a PDF or Word file.",
        "Paste the job description.",
    ]
    assert "analysis" not in screen.session_state
