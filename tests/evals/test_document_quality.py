"""The structural checks on an exported Word file, on files built to fail them."""

import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.models import FileType, ResumeDocument, Section, Span, SpanKind
from app.services.export import build_docx
from evals.document_quality import STRUCTURE_CHECKS, structure_checks

SOURCE = ResumeDocument(
    file_type=FileType.DOCX,
    page_count=None,
    spans=[
        Span(id="s0", text="Sam Placeholder", kind=SpanKind.LINE, section=Section.HEADER, order=0),
        Span(
            id="s1",
            text="Experience",
            kind=SpanKind.HEADING,
            section=Section.EXPERIENCE,
            order=1,
        ),
        Span(
            id="s2",
            text="Data Engineer, Example Corp | Mar 2022 - Present",
            kind=SpanKind.LINE,
            section=Section.EXPERIENCE,
            order=2,
        ),
        Span(
            id="s3",
            text="Built Python pipelines.",
            kind=SpanKind.BULLET,
            section=Section.EXPERIENCE,
            order=3,
        ),
    ],
)


def _save(doc: object) -> bytes:
    buffer = io.BytesIO()
    doc.save(buffer)  # type: ignore[attr-defined]
    return buffer.getvalue()


def test_the_app_export_passes_every_check() -> None:
    checks = structure_checks(build_docx(SOURCE, {}, {}, role_header_ids={"s2"}), SOURCE)
    assert list(checks) == list(STRUCTURE_CHECKS)
    assert all(checks.values()), checks


def test_a_plain_word_file_with_tables_and_headers_fails() -> None:
    doc = Document()
    doc.add_paragraph("Experience")  # a heading typed as a plain paragraph
    doc.add_paragraph("- Built Python pipelines.")  # a typed bullet
    doc.add_table(rows=1, cols=2)
    doc.sections[0].header.paragraphs[0].text = "Sam Placeholder"
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), "2")
    doc.sections[0]._sectPr.append(cols)
    doc.core_properties.language = ""
    checks = structure_checks(_save(doc), SOURCE)
    assert checks["no_tables"] is False
    assert checks["no_headers_or_footers"] is False
    assert checks["one_column"] is False
    assert checks["heading_styles"] is False
    assert checks["list_styles"] is False
    assert checks["language"] is False
    assert checks["no_text_boxes"] is True
