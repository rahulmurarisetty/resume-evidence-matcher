"""The Word export and the change list."""

import io
from datetime import date

import pytest
from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.shared import RGBColor

from app.models import AnalysisReport, ChangeKind, ResumeDocument, Section
from app.services.analysis import analyze
from app.services.export import (
    AcceptedRewrite,
    build_docx,
    export_lines,
    heading_text,
    list_changes,
    shown_text,
    split_dates,
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


def _roles(report: AnalysisReport) -> set[str]:
    return {r.header_span_id for r in report.profile.roles}


def _expected(resume: ResumeDocument, report: AnalysisReport) -> list[str]:
    roles = _roles(report)
    return [shown_text(s, s.text, is_role_line=s.id in roles) for s in resume.spans]


def _same_words(original: str, shown: str) -> bool:
    """A shown line keeps every word: only the separator before the dates may become a
    tab, and an all-capitals section heading may become its standard name."""
    if "\t" not in shown:
        return shown == original or heading_text(original) == shown
    left, dates = shown.split("\t")
    return original.startswith(left) and original.rstrip(" )").endswith(dates)


def test_export_keeps_every_line_in_order(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = sample
    doc = _open(_export(sample))
    texts = [p.text for p in doc.paragraphs]
    assert texts == _expected(resume, report)
    assert all(_same_words(s.text, t) for s, t in zip(resume.spans, texts, strict=True))
    assert texts[:3] == ["Jordan Example", resume.spans[1].text, "Summary"]
    # The role line's dates sit after a tab; nothing else in it changed.
    assert "Senior Data Engineer, Example Mutual Insurance\tMar 2022 - Present" in texts


def test_layout_is_plain_and_single_column(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    data = _export(sample)
    doc = _open(data)
    paragraphs = {p.text: p for p in doc.paragraphs}

    name = paragraphs["Jordan Example"]
    assert name.runs[0].bold and name.runs[0].font.size.pt == 18
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings == ["Summary", "Experience", "Skills", "Education"]
    role = paragraphs["Senior Data Engineer, Example Mutual Insurance\tMar 2022 - Present"]
    assert (
        role.runs[0].bold and role.runs[0].text == "Senior Data Engineer, Example Mutual Insurance"
    )
    assert not role.runs[1].bold
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
    expected = _expected(resume, sample[1])
    assert unchanged == [
        e for e, s in zip(expected, resume.spans, strict=True) if s.id not in {"s3", "s8"}
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
    texts = [p.text for p in doc.paragraphs]
    assert texts == _expected(resume, report)
    assert all(_same_words(s.text, t) for s, t in zip(resume.spans, texts, strict=True))
    assert doc.tables == []


def test_layout_looks_like_a_resume(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    doc = _open(_export(sample))
    normal = doc.styles["Normal"].paragraph_format
    # Tight single spacing, so a one-page resume stays one page.
    assert normal.space_after.pt == 0 and normal.line_spacing == 1.0
    heading = doc.styles["Heading 1"]
    assert heading.font.all_caps and heading.font.bold
    assert heading.font.color.rgb == RGBColor(0, 0, 0)
    section = doc.sections[0]
    assert (section.page_width.inches, section.page_height.inches) == (8.5, 11)
    assert round(section.left_margin.inches, 2) == 0.7
    first_heading = next(p for p in doc.paragraphs if p.style.name == "Heading 1")
    assert first_heading._p.pPr.find(f"{W}pBdr") is not None  # rule under the heading
    role = next(p for p in doc.paragraphs if "\t" in p.text)
    [stop] = list(role.paragraph_format.tab_stops)
    assert stop.alignment == WD_TAB_ALIGNMENT.RIGHT
    assert round(stop.position.inches, 2) == round(8.5 - 1.4, 2)
    skills = next(p for p in doc.paragraphs if p.text.startswith("Languages:"))
    assert skills.runs[0].text == "Languages:" and skills.runs[0].bold
    assert not skills.runs[1].bold and skills.text == "Languages: Python, SQL, Scala"


@pytest.mark.parametrize(
    ("text", "single", "expected"),
    [
        ("Data Engineer | Jun 2019 - Feb 2022", False, ("Data Engineer", "Jun 2019 - Feb 2022")),
        (
            "Analyst, Demo Corp, 03/2020 - 01/2023",
            False,
            ("Analyst, Demo Corp", "03/2020 - 01/2023"),
        ),
        ("Engineer (2019 - 2021)", False, ("Engineer", "2019 - 2021")),
        (
            "Developer | Jun 2021 \u2013 Till Date",
            False,
            ("Developer", "Jun 2021 \u2013 Till Date"),
        ),
        (
            "Example Institute, Hyderabad \u2013 2016",
            True,
            ("Example Institute, Hyderabad", "2016"),
        ),
        ("Example Institute, Hyderabad \u2013 2016", False, None),
        ("Built 40+ Airflow DAGs in 2021", False, None),
        ("Senior Data Engineer", False, None),
    ],
)
def test_split_dates(text: str, single: bool, expected: tuple[str, str] | None) -> None:
    assert split_dates(text, single=single) == expected


def test_education_degree_bold_and_year_right_aligned() -> None:
    markup = (
        "# Casey Example\ncasey@example.com\n## Education\n"
        "Bachelor of Technology in Computer Science\nExample Institute, Pune \u2013 2016\n"
    )
    resume, report = analyze(
        build_docx_resume(markup), "Requirements\n- Python and SQL experience required\n"
    )
    doc = _open(build_docx(resume, {}, {}, role_header_ids=_roles(report)))
    degree = next(p for p in doc.paragraphs if p.text.startswith("Bachelor"))
    assert degree.runs[0].bold
    assert "Example Institute, Pune\t2016" in [p.text for p in doc.paragraphs]


def test_language_title_and_real_styles(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    """v1.0 accessibility: the file says it is in English and what it is, and its
    headings and bullets are Word's own heading and list styles."""
    doc = _open(_export(sample))
    assert doc.core_properties.language == "en-US"
    assert doc.core_properties.title == "Resume"
    defaults = doc.styles.element.find(f"{W}docDefaults")
    lang = defaults.find(f"{W}rPrDefault/{W}rPr/{W}lang")
    assert lang is not None and lang.get(f"{W}val") == "en-US"
    resume, _ = sample
    section_headings = [s for s in resume.spans if s.kind.value == "heading"]
    styled = [p for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert len(styled) == len(section_headings)
    bullets = [s for s in resume.spans if s.kind.value == "bullet"]
    assert len([p for p in doc.paragraphs if p.style.name == "List Bullet"]) == len(bullets)
    # The list style is a real numbered list in Word, not a typed bullet character.
    assert all(not p.text.startswith(("•", "-", "*")) for p in doc.paragraphs)
