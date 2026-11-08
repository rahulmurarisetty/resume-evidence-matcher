"""The file formats each resume is rendered to before it goes through the app.

tests/builders.py turns the resume markup into real PDF and DOCX files in memory.
Both PDF bullet layouts are measured: the default style, where the glyph and the
text are one text run, and the "separate" style, where the glyph is drawn on its
own as Word's PDF export does.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tests.builders import PdfStyle, build_docx, build_pdf


@dataclass(frozen=True)
class Format:
    name: str
    family: str  # the --formats value that selects it: pdf or docx
    description: str
    render: Callable[[str], bytes]


def _pdf_inline(markup: str) -> bytes:
    return build_pdf(markup, PdfStyle())


def _pdf_separate(markup: str) -> bytes:
    return build_pdf(markup, PdfStyle(bullet_mode="separate"))


def _docx(markup: str) -> bytes:
    return build_docx(markup)


FORMATS: tuple[Format, ...] = (
    Format(
        "pdf_inline",
        "pdf",
        "PDF with the default PdfStyle: bullet glyph and text in one text run",
        _pdf_inline,
    ),
    Format(
        "pdf_separate",
        "pdf",
        'PDF with bullet_mode="separate": the glyph drawn on its own, as Word exports do',
        _pdf_separate,
    ),
    Format(
        "docx",
        "docx",
        "DOCX from python-docx: Heading 1 sections and List Bullet paragraphs",
        _docx,
    ),
)
FAMILIES = ("pdf", "docx")


def select_formats(families: Sequence[str]) -> list[Format]:
    unknown = sorted(set(families) - set(FAMILIES))
    if unknown:
        raise ValueError(f"unknown format {', '.join(unknown)}; use {' or '.join(FAMILIES)}")
    return [f for f in FORMATS if f.family in families]
