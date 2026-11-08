"""The Streamlit screen's helpers, run against the real API. Streamlit itself is
optional: the screen test skips when it isn't installed."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from tests.builders import build_docx, build_pdf
from tests.fakes import FakeLLMClient

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
    analysis = ui.create_analysis(client, "resume.pdf", pdf, data_engineer_jd)
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
    analysis = ui.create_analysis(client, "Resume.DOCX", build_docx(dotnet_markup), dotnet_jd)
    assert analysis["report"]["coverage"]["required"]["total"] == 6
    assert ui.mime_type("cv.pdf") == "application/pdf"
    assert ui.mime_type("cv") == "application/octet-stream"


def test_api_errors_carry_the_message(ui: ModuleType, client: TestClient) -> None:
    with pytest.raises(ui.ApiError, match="Paste the full job description"):
        ui.create_analysis(client, "r.pdf", b"%PDF-1.7 tiny", "too short")
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
    ui: ModuleType, tmp_path: Path, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    from app.config import Settings
    from app.main import create_app
    from tests.integration.test_edits_api import rewrite_handler

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=f"sqlite:///{tmp_path / 'ui.db'}",
        log_level="WARNING",
        semantic_matching="off",
        llm_enabled="on",
    )
    fake = FakeLLMClient(handler=rewrite_handler)
    with TestClient(create_app(settings, llm_client=fake)) as client:
        analysis = ui.create_analysis(
            client, "resume.pdf", build_pdf(data_engineer_markup), data_engineer_jd
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
    analysis = ui.create_analysis(client, "r.docx", build_docx(dotnet_markup), dotnet_jd)
    with pytest.raises(ui.ApiError, match="need Claude") as error:
        ui.request_suggestions(client, analysis["id"])
    assert error.value.code == "llm_disabled"
