"""The downloadable match report: what it says, and that the HTML is accessible on
its own (language, one h1, headings in order, tables with captions and header
cells, statuses in words, no scripts and no outside files)."""

import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser

import pytest

from app.models import AnalysisReport, ResumeDocument
from app.services.analysis import analyze
from app.services.match_report import (
    EMPLOYER_SYSTEMS_NOTE,
    STATUS_WORDS,
    STYLE,
    build_document,
    render_html,
    render_markdown,
)
from app.services.questions import all_questions
from tests.builders import build_pdf

CREATED = datetime(2026, 11, 8, 14, 30, tzinfo=UTC)
EXPIRES = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)
JOB = """Senior Data Engineer

About the role
We are looking for a hands-on data engineer to join our claims analytics team.

Requirements
- Strong Python and SQL
- Hands-on experience with PySpark on Databricks
- Experience with Kafka
- Only W2 candidates, no C2C.

Nice to have
- Experience with dbt
"""


@pytest.fixture(scope="module")
def analysis(data_engineer_markup: str) -> tuple[ResumeDocument, AnalysisReport]:
    return analyze(build_pdf(data_engineer_markup), JOB, today=date(2026, 11, 1))


def _document(analysis: tuple[ResumeDocument, AnalysisReport], answers: dict[str, str]) -> object:
    resume, report = analysis
    return build_document(
        report, all_questions(report, resume), answers, created_at=CREATED, expires_at=EXPIRES
    )


class _Outline(HTMLParser):
    """Collects what the accessibility checks look at."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.headings: list[int] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _outline(page: str) -> _Outline:
    parser = _Outline()
    parser.feed(page)
    return parser


def test_html_is_accessible_on_its_own(
    analysis: tuple[ResumeDocument, AnalysisReport],
) -> None:
    page = render_html(_document(analysis, {}))  # type: ignore[arg-type]
    outline = _outline(page)
    tags = [tag for tag, _ in outline.tags]
    assert page.startswith("<!DOCTYPE html>\n")
    assert ("html", {"lang": "en"}) in outline.tags
    assert outline.headings.count(1) == 1 and outline.headings[0] == 1
    # Headings never skip a level on the way down.
    for before, after in zip(outline.headings, outline.headings[1:], strict=False):
        assert after <= before + 1, outline.headings
    # Every table has a caption, and every header cell a scope.
    assert tags.count("table") == tags.count("caption") >= 2
    assert all(attrs.get("scope") in ("col", "row") for tag, attrs in outline.tags if tag == "th")
    # Nothing to run and nothing to load: no scripts, links, images, frames or URLs.
    for forbidden in ("script", "link", "img", "iframe", "object", "embed"):
        assert forbidden not in tags
    assert not any("src" in attrs or "href" in attrs for _, attrs in outline.tags)
    assert "http://" not in page and "https://" not in page and "url(" not in page
    assert "<title>Match report: Senior Data Engineer</title>" in page
    assert f"<style>{STYLE}</style>" in page
    # Dark text on white.
    assert "color:#1a1a1a;background:#ffffff" in STYLE


def test_statuses_and_evidence_are_written_in_words(
    analysis: tuple[ResumeDocument, AnalysisReport],
) -> None:
    _, report = analysis
    page = render_html(_document(analysis, {}))  # type: ignore[arg-type]
    text = " ".join(_outline(page).text)
    for match in report.matches:
        assert f"Status {STATUS_WORDS[match.status]}" in text.replace("</dt><dd>", " ")
    assert "Proven" in text and "Missing" in text
    assert "Evidence for Python (experience, page 1)" in text
    assert "Next step" in text


def test_report_has_every_part(analysis: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = analysis
    questions = all_questions(report, resume)
    gap = next(q for q in questions if q.kind == "gap")
    metric = next(q for q in questions if q.kind == "metric")
    answers = {gap.id: "Only in a course.", metric.id: "About 30 tables."}
    markdown = render_markdown(_document(analysis, answers))  # type: ignore[arg-type]
    for heading in (
        "# Match report: Senior Data Engineer",
        "## About this report",
        "## Coverage by priority",
        "## Requirements",
        "### Required",
        "### Preferred",
        "## Section order advice",
        "## Questions for you",
        "### Missing or related requirements",
        "### Bullets without a number",
        "## Terms noticed in the posting",
        "## Roles read from your resume",
        "## Warnings",
    ):
        assert f"\n{heading}\n" in f"\n{markdown}", heading
    assert EMPLOYER_SYSTEMS_NOTE in markdown
    assert "not a prediction of any employer's decision" in markdown
    assert "- Only W2 candidates, no C2C." in markdown
    assert "Only W2" not in markdown.split("## Terms noticed")[0]
    assert "- Your answer: Only in a course." in markdown
    assert "- Your answer: About 30 tables." in markdown
    assert "Table: Requirements per priority and status" in markdown
    assert "| Priority | Total | Proven | Partly shown |" in markdown
    # The intro sentence is a job duty, not a requirement.
    duties = markdown.split("### Job duties")[1].split("## Section order advice")[0]
    assert "We are looking for a hands-on data engineer" in duties
    assert "Made 2026-11-08 14:30 UTC" in markdown


def test_resume_text_is_escaped(analysis: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = analysis
    tricky = report.model_copy(deep=True)
    tricky.matches[0].requirement.text = "<script>alert(1)</script> *bold* $5 | pipe"
    document = build_document(
        tricky, all_questions(tricky, resume), {}, created_at=CREATED, expires_at=EXPIRES
    )
    page = render_html(document)
    assert "<script>" not in page and "&lt;script&gt;" in page
    markdown = render_markdown(document)
    assert r"\<script\>" in markdown and r"\*bold\*" in markdown and r"\$5 \| pipe" in markdown


def test_the_prose_follows_the_house_rules(
    analysis: tuple[ResumeDocument, AnalysisReport],
) -> None:
    markdown = render_markdown(_document(analysis, {}))  # type: ignore[arg-type]
    assert "\u2014" not in markdown
    assert not re.search(r"[\u201c\u201d\u2018\u2019]", markdown)
    assert "**" not in markdown
