"""Word export and the list of changes.

The export is rebuilt from the lines the app read, with the person's corrections
and accepted rewrites applied. Nothing else changes: no line is added, dropped or
reordered. Section headings are written in their standard form ("PROFESSIONAL
EXPERIENCE" becomes "Experience") so applicant tracking systems recognize them.

The file is a single column of plain paragraphs: the name, contact lines,
standard headings (shown in capitals with a rule under them), bold role and degree
lines, bold labels on "Label: values" lines, and Word's own bullet style, with tight
single spacing on Letter paper. A date range at the end of a role line moves to a
right-aligned tab stop, so the separator before it (" | ", a comma or a dash) is
replaced by a tab; the words and dates themselves don't change. It has no tables,
text boxes, headers, footers or images. Its language is set to English (en-US) and
its title to "Resume", so screen readers read it in the right language, and the
headings and bullets use Word's own Heading 1 and List Bullet styles, so they are
real headings and lists. The uploaded file is never stored, so it can't be
modified.
"""

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
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
DATED_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS, Section.EDUCATION}


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


# Layout. Letter paper, 0.7 inch margins, Calibri 10.5 pt with single spacing and no
# gap after ordinary lines, so a one-page resume stays one page.
_MARGIN = Inches(0.7)
_TEXT_WIDTH = Inches(8.5 - 2 * 0.7)
_BODY_SIZE = Pt(10.5)
_NAME_SIZE = Pt(18)
_HEADING_SIZE = Pt(11.5)
_FONT = "Calibri"
_BLACK = RGBColor(0, 0, 0)
LANGUAGE = "en-US"
TITLE = "Resume"

# A date range at the end of a line: "Jun 2021 - Till Date", "03/2020 - 01/2023",
# "2019 - 2021", "(2019 - 2021)". It moves to a right-aligned tab stop.
_MONTH = r"(?:[A-Za-z]{3,9}\.?\s+|\d{1,2}/)?"
_END = r"(?:" + _MONTH + r"\d{4}|present|current|now|till\s+date|to\s+date|today)"
_DATE_RANGE = re.compile(
    r"^(?P<left>.*?\S)\s*(?:\||,|\u2013|-)?\s*\(?(?P<dates>"
    + _MONTH
    + r"\d{4}\s*(?:-|\u2013|\u2014|to)\s*"
    + _END
    + r")\)?\s*$",
    re.IGNORECASE,
)
# A single year or month and year at the end of an education line: "..., 2016".
_SINGLE_DATE = re.compile(
    r"^(?P<left>.*?\S)\s*(?:\||,|\u2013|-)\s*\(?(?P<dates>" + _MONTH + r"\d{4})\)?\s*$"
)
# Degree lines in the education section are bold, like role lines.
_DEGREE = re.compile(
    r"^(bachelor|master|associate|doctor|diploma|b\.?\s?s\b|m\.?\s?s\b|b\.?\s?tech|m\.?\s?tech"
    r"|b\.?\s?e\b|m\.?\s?e\b|b\.?\s?a\b|m\.?\s?a\b|b\.?\s?sc|m\.?\s?sc|mba|ph\.?\s?d|bca|mca)",
    re.IGNORECASE,
)
# "Languages: Python, SQL" style lines get a bold label.
_LABEL = re.compile(r"^(?P<label>[A-Za-z][A-Za-z /&+.-]{0,40}?)\s*:\s*(?P<rest>\S.*)$")
_LABELED_ANYWHERE = ("environment", "client", "tech stack", "technologies", "tools")


def _set_font(run_or_style_font: object, size: Pt | None = None, bold: bool | None = None) -> None:
    font = run_or_style_font
    font.name = _FONT  # type: ignore[attr-defined]
    font.color.rgb = _BLACK  # type: ignore[attr-defined]
    if size is not None:
        font.size = size  # type: ignore[attr-defined]
    if bold is not None:
        font.bold = bold  # type: ignore[attr-defined]
    # Word keeps a separate font slot for East Asian text and the theme; set it too
    # so headings don't fall back to the template's light heading font.
    r_pr = font._element.get_or_add_rPr()  # type: ignore[attr-defined]
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        r_fonts.set(qn(attr), _FONT)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        r_fonts.attrib.pop(qn(attr), None)


def _tight(paragraph_format: object, before: float = 0, after: float = 0) -> None:
    fmt = paragraph_format
    fmt.space_before = Pt(before)  # type: ignore[attr-defined]
    fmt.space_after = Pt(after)  # type: ignore[attr-defined]
    fmt.line_spacing = 1.0  # type: ignore[attr-defined]


def _bottom_border(paragraph: object) -> None:
    p_pr = paragraph._p.get_or_add_pPr()  # type: ignore[attr-defined]
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    p_pr.append(borders)


def _set_language(doc: object) -> None:
    """English (en-US) as the language of every run, in the document defaults that
    every style inherits."""
    styles_element = doc.styles.element  # type: ignore[attr-defined]
    defaults = styles_element.find(qn("w:docDefaults"))
    if defaults is None:
        defaults = OxmlElement("w:docDefaults")
        styles_element.insert(0, defaults)
    r_pr_default = defaults.find(qn("w:rPrDefault"))
    if r_pr_default is None:
        r_pr_default = OxmlElement("w:rPrDefault")
        defaults.insert(0, r_pr_default)
    r_pr = r_pr_default.find(qn("w:rPr"))
    if r_pr is None:
        r_pr = OxmlElement("w:rPr")
        r_pr_default.append(r_pr)
    lang = r_pr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        r_pr.append(lang)
    lang.set(qn("w:val"), LANGUAGE)
    lang.set(qn("w:eastAsia"), LANGUAGE)
    doc.core_properties.language = LANGUAGE  # type: ignore[attr-defined]


def _style_document(doc: object) -> None:
    _set_language(doc)
    styles = doc.styles  # type: ignore[attr-defined]
    normal = styles["Normal"]
    _set_font(normal.font, _BODY_SIZE)
    _tight(normal.paragraph_format)

    heading = styles["Heading 1"]
    _set_font(heading.font, _HEADING_SIZE, bold=True)
    # Displayed in capitals, stored in sentence case, so applicant tracking systems
    # still read "Experience".
    heading.font.all_caps = True
    _tight(heading.paragraph_format, before=9, after=3)
    heading.paragraph_format.keep_with_next = True

    bullet = styles["List Bullet"]
    _set_font(bullet.font, _BODY_SIZE)
    _tight(bullet.paragraph_format, after=1)
    bullet.paragraph_format.left_indent = Inches(0.25)
    bullet.paragraph_format.first_line_indent = Inches(-0.18)

    for section in doc.sections:  # type: ignore[attr-defined]
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = section.bottom_margin = _MARGIN
        section.left_margin = section.right_margin = _MARGIN


def split_dates(text: str, *, single: bool = False) -> tuple[str, str] | None:
    """Split "Title | Jun 2021 - Present" into ("Title", "Jun 2021 - Present").
    With single=True a lone trailing year or month and year also counts, for
    education lines. None when the line doesn't end with dates."""
    match = _DATE_RANGE.match(text) or (_SINGLE_DATE.match(text) if single else None)
    if match is None:
        return None
    return match.group("left").rstrip(" |,-\u2013"), match.group("dates")


def _splits_dates(span: Span, is_role_line: bool) -> bool:
    if span.kind is SpanKind.BULLET:
        return False
    return is_role_line or span.section in DATED_SECTIONS


def shown_text(span: Span, text: str, *, is_role_line: bool = False) -> str:
    """The line exactly as the Word file shows it: a standard heading, the dates of a
    role or education line after a tab, and every other line unchanged."""
    if span.kind is SpanKind.HEADING and section_for_heading(text) is not None:
        return heading_text(text)
    if _splits_dates(span, is_role_line):
        parts = split_dates(text, single=span.section is Section.EDUCATION)
        if parts is not None:
            return f"{parts[0]}\t{parts[1]}"
    return text


def _add_dated_line(doc: object, parts: tuple[str, str], *, bold: bool, gap: float) -> None:
    paragraph = doc.add_paragraph()  # type: ignore[attr-defined]
    _tight(paragraph.paragraph_format, before=gap)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.tab_stops.add_tab_stop(_TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    paragraph.add_run(parts[0]).bold = bold
    paragraph.add_run("\t" + parts[1])


def _add_labeled_line(doc: object, text: str) -> bool:
    """Bold the label of a "Label: values" line, keeping the text exactly as written."""
    match = _LABEL.match(text)
    if match is None or len(match.group("label").split()) > 4:
        return False
    colon = text.index(":") + 1
    paragraph = doc.add_paragraph()  # type: ignore[attr-defined]
    paragraph.paragraph_format.space_after = Pt(1)
    paragraph.add_run(text[:colon]).bold = True
    paragraph.add_run(text[colon:])
    return True


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
    properties.title = TITLE
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

    _style_document(doc)

    name_written = False
    # Space goes above a role's first line, except straight after a section heading
    # or another role line.
    after_header = True
    for line in export_lines(resume, corrections, rewrites):
        span, text = line.span, line.text
        gap = 0.0 if after_header else 6.0
        is_section_heading = span.kind is SpanKind.HEADING and section_for_heading(text) is not None
        is_role_line = not is_section_heading and (
            span.kind is SpanKind.HEADING or span.id in roles
        )
        parts = (
            split_dates(text, single=span.section is Section.EDUCATION)
            if _splits_dates(span, is_role_line)
            else None
        )

        if is_section_heading:
            heading = doc.add_heading(heading_text(text), level=1)
            _bottom_border(heading)
        elif parts is not None:
            # Role and education lines with dates: words on the left, dates on the right.
            _add_dated_line(doc, parts, bold=is_role_line, gap=gap if is_role_line else 0)
        elif is_role_line:
            paragraph = doc.add_paragraph()
            _tight(paragraph.paragraph_format, before=gap)
            paragraph.paragraph_format.keep_with_next = True
            paragraph.add_run(text).bold = True
        elif span.kind is SpanKind.BULLET:
            doc.add_paragraph(text, style="List Bullet")
        elif span.section is Section.HEADER and not name_written:
            paragraph = doc.add_paragraph()
            _tight(paragraph.paragraph_format, after=2)
            run = paragraph.add_run(text)
            run.bold = True
            run.font.size = _NAME_SIZE
        elif (
            span.section is Section.SKILLS or text.lower().startswith(_LABELED_ANYWHERE)
        ) and _add_labeled_line(doc, text):
            pass
        elif span.section is Section.EDUCATION and _DEGREE.match(text):
            paragraph = doc.add_paragraph()
            _tight(paragraph.paragraph_format, before=gap)
            paragraph.add_run(text).bold = True
        else:
            paragraph = doc.add_paragraph(text)
            if span.section is Section.HEADER:
                paragraph.paragraph_format.space_after = Pt(1)
        if span.section is Section.HEADER:
            name_written = True
        after_header = is_section_heading or is_role_line

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
