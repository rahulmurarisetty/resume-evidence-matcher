"""Build realistic PDF and DOCX resumes from a small markup format.

Used by the tests and by scripts/make_samples.py. Markup:

    # Name               large bold line
    ## Section           section heading
    ### Role line        bold line
    - bullet text        bullet, wrapped with a hanging indent like Word produces
    anything else        plain line, wrapped
"""

import io
from dataclasses import dataclass

import pymupdf
from docx import Document
from docx.shared import Pt


@dataclass(frozen=True)
class PdfStyle:
    # "inline": glyph and text in one text run ("• Built ...").
    # "separate": glyph drawn on its own, text placed after it, as Word exports do.
    bullet_mode: str = "inline"
    glyph: str = "•"
    page_width: float = 612
    page_height: float = 792
    margin: float = 54
    font_size: float = 10.5


def _wrap(text: str, width: float, fontname: str, size: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontname=fontname, fontsize=size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_pdf(markup: str, style: PdfStyle | None = None) -> bytes:
    style = style or PdfStyle()
    doc = pymupdf.open()
    page = doc.new_page(width=style.page_width, height=style.page_height)
    left = style.margin
    usable = style.page_width - 2 * style.margin
    leading = style.font_size * 1.35
    y = style.margin

    def ensure_room(lines: int = 1) -> None:
        nonlocal page, y
        if y + leading * lines > style.page_height - style.margin:
            page = doc.new_page(width=style.page_width, height=style.page_height)
            y = style.margin

    def write(x: float, text: str, font: str = "helv", size: float | None = None) -> None:
        page.insert_text((x, y), text, fontname=font, fontsize=size or style.font_size)

    for raw in markup.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            ensure_room()
            y += leading * 0.3
            write(left, line[4:], font="hebo")
            y += leading
        elif line.startswith("## "):
            ensure_room(2)
            y += leading * 0.8
            write(left, line[3:].upper(), font="hebo", size=style.font_size + 1.5)
            y += leading * 1.2
        elif line.startswith("# "):
            write(left, line[2:], font="hebo", size=style.font_size + 8)
            y += leading * 1.8
        elif line.startswith("- "):
            glyph_x, text_x = left + 6, left + 18
            wrapped = _wrap(line[2:], usable - (text_x - left), "helv", style.font_size)
            ensure_room(len(wrapped))
            for i, part in enumerate(wrapped):
                if i == 0 and style.bullet_mode == "inline":
                    write(glyph_x, f"{style.glyph} {part}")
                elif i == 0:
                    write(glyph_x, style.glyph)
                    write(text_x, part)
                else:
                    write(text_x if style.bullet_mode == "separate" else glyph_x + 8, part)
                y += leading
        else:
            for part in _wrap(line, usable, "helv", style.font_size):
                ensure_room()
                write(left, part)
                y += leading

    data: bytes = doc.tobytes()
    doc.close()
    return data


def build_docx(markup: str, skills_as_table: bool = False) -> bytes:
    doc = Document()
    in_skills = False
    table = None
    for raw in markup.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            run = doc.add_paragraph().add_run(line[4:])
            run.bold = True
        elif line.startswith("## "):
            title = line[3:]
            doc.add_heading(title, level=1)
            in_skills = "skill" in title.lower()
            table = None
        elif line.startswith("# "):
            run = doc.add_paragraph().add_run(line[2:])
            run.bold = True
            run.font.size = Pt(18)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif in_skills and skills_as_table and ":" in line:
            label, values = line.split(":", 1)
            if table is None:
                table = doc.add_table(rows=0, cols=2)
            cells = table.add_row().cells
            cells[0].text = label.strip()
            cells[1].text = values.strip()
        else:
            doc.add_paragraph(line)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
