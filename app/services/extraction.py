"""Turn an uploaded PDF or DOCX resume into ordered spans with their source location.

Files are parsed in memory and never written to disk.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field

import pymupdf
from docx import Document as load_docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models import FileType, ResumeDocument, Section, Span, SpanKind
from app.services.structure import RANGE_RE
from app.services.text import (
    BULLET_ONLY_RE,
    PAGE_FOOTER_RE,
    normalize,
    section_for_heading,
    strip_bullet,
)


class ExtractionError(ValueError):
    """A problem with the uploaded file that the user can fix."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExtractionLimits:
    max_pdf_pages: int = 10
    max_docx_uncompressed_bytes: int = 50 * 1024 * 1024
    max_docx_entries: int = 2000


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------


def sniff_file_type(data: bytes, limits: ExtractionLimits) -> FileType:
    """Decide the file type from its bytes, not its name or the browser's MIME type."""
    if data.startswith(b"%PDF-"):
        return FileType.PDF
    if data.startswith(b"PK\x03\x04"):
        _check_docx_archive(data, limits)
        return FileType.DOCX
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise ExtractionError(
            "legacy_doc", "Old .doc files aren't supported. Save the resume as .docx or PDF."
        )
    raise ExtractionError("unsupported_type", "Upload the resume as a PDF or .docx file.")


def _check_docx_archive(data: bytes, limits: ExtractionLimits) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ExtractionError("corrupt_file", "The .docx file is damaged.") from exc

    if "word/document.xml" not in {info.filename for info in infos}:
        raise ExtractionError("unsupported_type", "This zip file isn't a Word document.")
    if len(infos) > limits.max_docx_entries:
        raise ExtractionError("file_too_complex", "The .docx file has too many parts.")
    if sum(info.file_size for info in infos) > limits.max_docx_uncompressed_bytes:
        raise ExtractionError("file_too_large", "The .docx file is too large once unpacked.")


# ---------------------------------------------------------------------------
# Span assembly shared by both formats
# ---------------------------------------------------------------------------


@dataclass
class _Builder:
    spans: list[Span] = field(default_factory=list)
    section: Section = Section.HEADER

    def add(self, text: str, kind: SpanKind, page: int | None) -> None:
        text = normalize(text)
        if not text:
            return
        if kind is SpanKind.HEADING:
            self.section = section_for_heading(text) or self.section
        self.spans.append(
            Span(
                id=f"s{len(self.spans)}",
                text=text,
                kind=kind,
                section=self.section,
                page=page,
                order=len(self.spans),
            )
        )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@dataclass
class _PdfLine:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    bold: bool = False  # every character on the line is in a bold font


@dataclass
class _OpenBlock:
    """A bullet or paragraph that may continue on the next line."""

    kind: SpanKind
    text: str
    x0: float  # left edge of the first line (the glyph, for bullets)
    last_x1: float  # right edge of the most recent line
    y1: float
    height: float
    bold: bool = False  # the most recent line is bold


_BOLD_FLAG = 16  # PyMuPDF's span flag for a bold font
_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demibold", re.IGNORECASE)


def _is_bold(span: dict[str, object]) -> bool:
    flags = span.get("flags", 0)
    bold_flag = isinstance(flags, int) and bool(flags & _BOLD_FLAG)
    return bold_flag or bool(_BOLD_NAME.search(str(span.get("font", ""))))


def _pdf_lines(page: "pymupdf.Page") -> list[_PdfLine]:
    lines: list[_PdfLine] = []
    # Keep the PDF's own block order. Sorting by position interleaves the
    # columns of two-column resumes.
    for block in page.get_text("dict")["blocks"]:  # type: ignore[no-untyped-call]
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            x0, y0, x1, y1 = line["bbox"]
            written = [span for span in line["spans"] if span["text"].strip()]
            bold = bool(written) and all(_is_bold(span) for span in written)
            lines.append(_PdfLine(text=text, x0=x0, x1=x1, y0=y0, y1=y1, bold=bold))
    return _merge_split_bullets(lines)


def _merge_split_bullets(lines: list[_PdfLine]) -> list[_PdfLine]:
    """Some PDFs store the bullet glyph and the bullet text as separate lines on the
    same baseline. Join them so the text keeps its bullet."""
    merged: list[_PdfLine] = []
    for line in lines:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and BULLET_ONLY_RE.match(prev.text)
            and abs(prev.y0 - line.y0) < 2
            and line.x0 > prev.x0
        ):
            merged[-1] = _PdfLine(
                f"{prev.text.strip()} {line.text}", prev.x0, line.x1, prev.y0, line.y1, line.bold
            )
        else:
            merged.append(line)
    return merged


_MAX_HEADER_WORDS = 14


def _starts_new_line_block(block: _OpenBlock, line: _PdfLine, text: str, right_edge: float) -> bool:
    """A short line that a paragraph above it doesn't wrap into: a line in bold after
    a regular one (or the other way round), as role headers are, or a short line with
    a date range ("Software Engineer, Example Corp | Jul 2018 - Dec 2019")."""
    if line.bold != block.bold:
        return True
    short = line.x1 < right_edge - 36 and len(text.split()) <= _MAX_HEADER_WORDS
    return short and not text[:1].islower() and RANGE_RE.search(text) is not None


def _continues(block: _OpenBlock, line: _PdfLine, text: str, right_edge: float) -> bool:
    """Is this line the wrapped continuation of the open bullet or paragraph?"""
    gap = line.y0 - block.y1
    if gap < -1 or gap > block.height * 0.9:
        return False
    mid_sentence = text[:1].islower() or block.text.rstrip().endswith((",", "-", "&"))
    if block.kind is SpanKind.BULLET:
        # Wrapped bullet lines are indented past the glyph.
        return line.x0 > block.x0 + 2 or mid_sentence
    if not mid_sentence and _starts_new_line_block(block, line, text, right_edge):
        return False
    # A paragraph wraps when the previous line ran to the right margin and the
    # next one starts at the same left edge.
    same_left = abs(line.x0 - block.x0) <= 2
    ran_full_width = block.last_x1 >= right_edge - 36
    return same_left and (ran_full_width or mid_sentence)


def extract_pdf(data: bytes, limits: ExtractionLimits) -> ResumeDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception as exc:  # PyMuPDF raises several exception types for bad files
        raise ExtractionError("corrupt_file", "The PDF couldn't be opened.") from exc

    with doc:
        if doc.needs_pass:
            raise ExtractionError("encrypted", "The PDF is password protected.")
        if doc.page_count > limits.max_pdf_pages:
            raise ExtractionError(
                "too_many_pages",
                f"The PDF has {doc.page_count} pages. The limit is {limits.max_pdf_pages}.",
            )

        builder = _Builder()
        pages = [_pdf_lines(doc[page_index]) for page_index in range(doc.page_count)]
        # The right margin is measured over the whole document: on a page with only
        # short lines (the end of an education section) every line would otherwise
        # look full width and be joined to the one before it.
        right_edge = max((line.x1 for lines in pages for line in lines), default=0.0)
        for page_index, lines in enumerate(pages):
            page_no = page_index + 1
            block: _OpenBlock | None = None

            def flush(page_no: int = page_no) -> None:
                nonlocal block
                if block is not None:
                    builder.add(block.text, block.kind, page_no)
                    block = None

            for line in lines:
                raw = normalize(line.text)
                if not raw or PAGE_FOOTER_RE.match(raw):
                    continue
                text, is_bullet = strip_bullet(raw)
                height = line.y1 - line.y0

                if not is_bullet and section_for_heading(text):
                    flush()
                    builder.add(text, SpanKind.HEADING, page_no)
                elif is_bullet:
                    flush()
                    block = _OpenBlock(
                        SpanKind.BULLET, text, line.x0, line.x1, line.y1, height, line.bold
                    )
                elif block is not None and _continues(block, line, text, right_edge):
                    joiner = "" if block.text.endswith("-") else " "
                    block.text = f"{block.text}{joiner}{text}"
                    block.last_x1 = line.x1
                    block.y1 = line.y1
                    block.bold = line.bold
                else:
                    flush()
                    block = _OpenBlock(
                        SpanKind.LINE, text, line.x0, line.x1, line.y1, height, line.bold
                    )
            flush()

        page_count = doc.page_count

    _require_text(builder.spans)
    return ResumeDocument(file_type=FileType.PDF, page_count=page_count, spans=builder.spans)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _is_docx_bullet(paragraph: Paragraph) -> bool:
    style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
    if "list" in style_name.lower():
        return True
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.numPr is not None


def _is_docx_heading(paragraph: Paragraph, text: str) -> bool:
    style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
    return section_for_heading(text) is not None or (
        style_name.lower().startswith("heading") and len(text) <= 60
    )


def _table_row_text(row: object) -> str:
    """One line per table row. Two-column skills tables read as 'Label: values'."""
    cells: list[str] = []
    seen: set[int] = set()
    for cell in row.cells:  # type: ignore[attr-defined]
        # Merged cells repeat; read each underlying cell once.
        if id(cell._tc) in seen:
            continue
        seen.add(id(cell._tc))
        text = "; ".join(normalize(p.text) for p in cell.paragraphs if p.text.strip())
        if text:
            cells.append(text)
    if len(cells) == 2 and len(cells[0].split()) <= 4:
        return f"{cells[0]}: {cells[1]}"
    return " | ".join(cells)


def _iter_docx_blocks(doc: object) -> list[Paragraph | str]:
    """Body paragraphs and table rows in reading order. Skills tables are common in
    resumes; each row comes back as plain text and is never treated as a heading."""
    blocks: list[Paragraph | str] = []
    for block in doc.iter_inner_content():  # type: ignore[attr-defined]
        if isinstance(block, Paragraph):
            blocks.append(block)
        elif isinstance(block, Table):
            blocks.extend(text for row in block.rows if (text := _table_row_text(row)))
    return blocks


def extract_docx(data: bytes) -> ResumeDocument:
    try:
        doc = load_docx(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError("corrupt_file", "The .docx file couldn't be opened.") from exc

    builder = _Builder()
    for paragraph in _iter_docx_blocks(doc):
        if isinstance(paragraph, str):
            builder.add(paragraph, SpanKind.LINE, None)
            continue
        # Soft line breaks inside one paragraph are still one bullet.
        raw = normalize(paragraph.text)
        if not raw:
            continue
        text, has_glyph = strip_bullet(raw)
        if not has_glyph and _is_docx_heading(paragraph, text):
            builder.add(text, SpanKind.HEADING, None)
        elif has_glyph or _is_docx_bullet(paragraph):
            builder.add(text, SpanKind.BULLET, None)
        else:
            builder.add(text, SpanKind.LINE, None)

    _require_text(builder.spans)
    return ResumeDocument(file_type=FileType.DOCX, page_count=None, spans=builder.spans)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _require_text(spans: list[Span]) -> None:
    if sum(len(s.text) for s in spans) < 50:
        raise ExtractionError(
            "no_text",
            "No readable text was found. If this is a scanned image, export the resume "
            "from Word or Google Docs instead. Scanned files aren't supported yet.",
        )


def extract_resume(data: bytes, limits: ExtractionLimits | None = None) -> ResumeDocument:
    limits = limits or ExtractionLimits()
    file_type = sniff_file_type(data, limits)
    if file_type is FileType.PDF:
        return extract_pdf(data, limits)
    return extract_docx(data)
