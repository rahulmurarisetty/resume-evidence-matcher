"""Word export and the list of changes.

The export is rebuilt from the lines the app read, with the person's corrections
and accepted rewrites applied. Nothing else changes: no line is added, dropped or
reordered. Section headings are written in their standard form ("PROFESSIONAL
EXPERIENCE" becomes "Experience") so applicant tracking systems recognize them.

The file is a single column of plain paragraphs: the name, contact lines,
standard headings, bold role lines and Word's own bullet style. It has no tables,
text boxes, headers, footers or images. The uploaded file is never stored, so it
can't be modified.
"""

import io
from collections.abc import Mapping
from dataclasses import dataclass

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.shared import Inches, Pt, RGBColor

from app.models import ChangeKind, ResumeDocument, Section, Span, SpanKind
from app.services.text import section_for_heading

STANDARD_HEADINGS = {
    Section.SUMMARY: "Summary",
    Section.EXPERIENCE: "Experience",
    Section.PROJECTS: "Projects",
    Section.SKILLS: "Skills",
    Section.EDUCATION: "Education",
    Section.CERTIFICATIONS: "Certifications",
}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class AcceptedRewrite:
    suggestion_id: str
    requirement_id: str
    text: str


@dataclass(frozen=True)
class Change:
    span_id: str
    section: Section
    kind: ChangeKind
    before: str
    after: str
    suggestion_id: str | None = None
    requirement_id: str | None = None


@dataclass(frozen=True)
class ExportLine:
    span: Span
    text: str


def export_lines(
    resume: ResumeDocument,
    corrections: Mapping[str, str],
    rewrites: Mapping[str, AcceptedRewrite],
) -> list[ExportLine]:
    """Every line in reading order: an accepted rewrite, else the correction, else
    the text as read."""
    lines: list[ExportLine] = []
    for span in resume.spans:
        text = corrections.get(span.id, span.text)
        if span.id in rewrites:
            text = rewrites[span.id].text
        lines.append(ExportLine(span, text))
    return lines


def list_changes(
    resume: ResumeDocument,
    corrections: Mapping[str, str],
    rewrites: Mapping[str, AcceptedRewrite],
) -> list[Change]:
    """Every difference between the export and the text as read, in reading order.
    A corrected line that also has an accepted rewrite lists both."""
    changes: list[Change] = []
    for span in resume.spans:
        corrected = corrections.get(span.id)
        if corrected is not None and corrected != span.text:
            changes.append(
                Change(span.id, span.section, ChangeKind.CORRECTION, span.text, corrected)
            )
        rewrite = rewrites.get(span.id)
        if rewrite is not None:
            before = corrected if corrected is not None else span.text
            changes.append(
                Change(
                    span.id,
                    span.section,
                    ChangeKind.REWRITE,
                    before,
                    rewrite.text,
                    suggestion_id=rewrite.suggestion_id,
                    requirement_id=rewrite.requirement_id,
                )
            )
    return changes


def heading_text(text: str) -> str:
    """The standard heading for a known section, else the heading as written, with
    all-capitals headings written in sentence case."""
    section = section_for_heading(text)
    if section is not None and section in STANDARD_HEADINGS:
        return STANDARD_HEADINGS[section]
    return text.capitalize() if text.isupper() else text


def build_docx(
    resume: ResumeDocument,
    corrections: Mapping[str, str],
    rewrites: Mapping[str, AcceptedRewrite],
    *,
    role_header_ids: set[str] | None = None,
) -> bytes:
    roles = role_header_ids or set()
    doc = Document()

    # No personal or tool metadata in the file's properties.
    properties = doc.core_properties
    properties.author = ""
    properties.last_modified_by = ""
    properties.title = "Resume"
    properties.subject = ""
    properties.keywords = ""
    properties.comments = ""
    properties.category = ""
    # The default template carries a thumbnail picture. Drop it so the file holds no
    # image at all.
    package_rels = doc.part.package.rels
    for rel_id, rel in list(package_rels.items()):
        if rel.reltype == RELATIONSHIP_TYPE.THUMBNAIL:
            package_rels.pop(rel_id)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    heading_style = doc.styles["Heading 1"]
    heading_style.font.color.rgb = RGBColor(0, 0, 0)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(0.75)
        section.left_margin = section.right_margin = Inches(0.75)

    name_written = False
    for line in export_lines(resume, corrections, rewrites):
        span, text = line.span, line.text
        if span.kind is SpanKind.HEADING and section_for_heading(text) is not None:
            doc.add_heading(heading_text(text), level=1)
        elif span.kind is SpanKind.HEADING or span.id in roles:
            # Word "Heading 2" role lines and role header lines are bold paragraphs.
            doc.add_paragraph().add_run(text).bold = True
        elif span.kind is SpanKind.BULLET:
            doc.add_paragraph(text, style="List Bullet")
        elif span.section is Section.HEADER and not name_written:
            run = doc.add_paragraph().add_run(text)
            run.bold = True
            run.font.size = Pt(16)
        else:
            doc.add_paragraph(text)
        if span.section is Section.HEADER:
            name_written = True

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
