"""The Word export and the change list."""

import io
from datetime import date

import pytest
from docx import Document

from app.models import AnalysisReport, ChangeKind, ResumeDocument, Section
from app.services.analysis import analyze
from app.services.export import (
    AcceptedRewrite,
    build_docx,
    export_lines,
    heading_text,
    list_changes,
)
from tests.builders import build_docx as build_docx_resume
from tests.builders import build_pdf

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REWRITE = AcceptedRewrite("sug1", "r2", "Orchestrated 40+ Airflow DAGs with SLA alerts.")
CORRECTION = "Data engineer with six years of experience building batch pipelines."


@pytest.fixture(scope="module")
def sample(
    data_engineer_markup: str, data_engineer_jd: str
) -> tuple[ResumeDocument, AnalysisReport]:
    return analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=date(2026, 11, 8))


def _open(data: bytes):  # type: ignore[no-untyped-def]
    return Document(io.BytesIO(data))


def _export(sample: tuple[ResumeDocument, AnalysisReport], **edits: object) -> bytes:
    resume, report = sample
    return build_docx(
        resume,
        edits.get("corrections", {}),  # type: ignore[arg-type]
        edits.get("rewrites", {}),  # type: ignore[arg-type]
        role_header_ids={role.header_span_id for role in report.profile.roles},
    )


def test_export_keeps_every_line_in_order(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, _ = sample
    doc = _open(_export(sample))
    texts = [p.text for p in doc.paragraphs]
    expected = [heading_text(s.text) if s.kind.value == "heading" else s.text for s in resume.spans]
    assert texts == expected
    assert texts[:3] == ["Jordan Example", resume.spans[1].text, "Summary"]


def test_layout_is_plain_and_single_column(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    data = _export(sample)
    doc = _open(data)
    paragraphs = {p.text: p for p in doc.paragraphs}

    name = paragraphs["Jordan Example"]
    assert name.runs[0].bold and name.runs[0].font.size.pt == 16
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings == ["Summary", "Experience", "Skills", "Education"]
    role = paragraphs["Senior Data Engineer, Example Mutual Insurance | Mar 2022 - Present"]
    assert role.runs[0].bold
    bullets = [p.text for p in doc.paragraphs if p.style.name == "List Bullet"]
    assert len(bullets) == 8
    assert bullets[0].startswith("Built PySpark jobs on Databricks")
    assert paragraphs["Languages: Python, SQL, Scala"].style.name == "Normal"

    # Nothing an applicant tracking system can trip over.
    assert doc.tables == []
    assert len(doc.inline_shapes) == 0
    assert len(doc.sections) == 1
    section = doc.sections[0]
    assert section.header.is_linked_to_previous and section.footer.is_linked_to_previous
    columns = section._sectPr.findall(f"{W}cols")
    assert all(int(c.get(f"{W}num", "1")) == 1 for c in columns)
    parts = [str(part.partname) for part in doc.part.package.iter_parts()]
    assert not [p for p in parts if "header" in p or "footer" in p or "media" in p]
    assert not [p for p in parts if p.endswith((".jpeg", ".jpg", ".png", ".emf", ".wmf"))]
    body = doc.element.body.xml
    assert "txbxContent" not in body and "w:drawing" not in body and "w:pict" not in body
    assert doc.core_properties.author == ""
    assert doc.core_properties.comments == ""


def test_corrections_and_rewrites_are_applied(
    sample: tuple[ResumeDocument, AnalysisReport],
) -> None:
    resume, _ = sample
    by_id = {s.id: s for s in resume.spans}
    doc = _open(_export(sample, corrections={"s3": CORRECTION}, rewrites={"s8": REWRITE}))
    texts = [p.text for p in doc.paragraphs]
    assert CORRECTION in texts and by_id["s3"].text not in texts
    assert REWRITE.text in texts and by_id["s8"].text not in texts
    # Only those two lines differ.
    assert len(texts) == len(resume.spans)
    unchanged = [t for t, s in zip(texts, resume.spans, strict=True) if s.id not in {"s3", "s8"}]
    assert unchanged == [
        heading_text(s.text) if s.kind.value == "heading" else s.text
        for s in resume.spans
        if s.id not in {"s3", "s8"}
    ]


def test_a_rewrite_replaces_a_corrected_line(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, _ = sample
    corrections = {"s8": "Scheduled and monitored 40+ Airflow DAGs with SLA alerts."}
    lines = export_lines(resume, corrections, {"s8": REWRITE})
    assert next(line.text for line in lines if line.span.id == "s8") == REWRITE.text
    changes = list_changes(resume, corrections, {"s8": REWRITE})
    assert [(c.kind, c.before, c.after) for c in changes] == [
        (ChangeKind.CORRECTION, resume.spans[8].text, corrections["s8"]),
        (ChangeKind.REWRITE, corrections["s8"], REWRITE.text),
    ]


def test_change_list(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, _ = sample
    original = {s.id: s.text for s in resume.spans}
    changes = list_changes(
        resume,
        # A "correction" equal to the original isn't a change.
        {"s3": CORRECTION, "s16": original["s16"]},
        {"s8": REWRITE},
    )
    assert [(c.span_id, c.kind, c.section) for c in changes] == [
        ("s3", ChangeKind.CORRECTION, Section.SUMMARY),
        ("s8", ChangeKind.REWRITE, Section.EXPERIENCE),
    ]
    assert changes[0].before == original["s3"] and changes[0].after == CORRECTION
    assert changes[1].before == original["s8"] and changes[1].after == REWRITE.text
    assert (changes[1].suggestion_id, changes[1].requirement_id) == ("sug1", "r2")
    assert list_changes(resume, {}, {}) == []


def test_standard_headings() -> None:
    assert heading_text("PROFESSIONAL EXPERIENCE") == "Experience"
    assert heading_text("Technical Skills") == "Skills"
    assert heading_text("Licenses and Certifications") == "Certifications"
    assert heading_text("AWARDS") == "Awards"
    assert heading_text("Volunteering") == "Volunteering"


def test_word_resume_with_role_headings(dotnet_markup: str, dotnet_jd: str) -> None:
    resume, report = analyze(build_docx_resume(dotnet_markup), dotnet_jd, today=date(2026, 11, 8))
    data = build_docx(
        resume, {}, {}, role_header_ids={r.header_span_id for r in report.profile.roles}
    )
    doc = _open(data)
    assert [p.text for p in doc.paragraphs] == [
        heading_text(s.text)
        if s.kind.value == "heading" and heading_text(s.text) != s.text
        else s.text
        for s in resume.spans
    ]
    assert doc.tables == []
