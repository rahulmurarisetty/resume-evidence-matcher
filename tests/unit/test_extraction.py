import io
import zipfile

import pymupdf
import pytest

from app.models import FileType, Section, SpanKind
from app.services.extraction import ExtractionError, ExtractionLimits, extract_resume
from tests.builders import PdfStyle, build_docx, build_pdf


def _texts(markup: str, kind: SpanKind, data: bytes) -> list[str]:
    return [s.text for s in extract_resume(data).spans if s.kind is kind]


@pytest.mark.parametrize("bullet_mode", ["inline", "separate"])
@pytest.mark.parametrize("glyph", ["•", "", "-"])
def test_pdf_wrapped_bullets_come_back_whole(
    data_engineer_markup: str, bullet_mode: str, glyph: str
) -> None:
    data = build_pdf(data_engineer_markup, PdfStyle(bullet_mode=bullet_mode, glyph=glyph))
    bullets = _texts(data_engineer_markup, SpanKind.BULLET, data)
    expected = [line[2:] for line in data_engineer_markup.splitlines() if line.startswith("- ")]
    assert bullets == expected


def test_pdf_sections_and_pages(data_engineer_markup: str) -> None:
    doc = extract_resume(build_pdf(data_engineer_markup))
    assert doc.file_type is FileType.PDF
    assert doc.page_count == 1
    assert doc.sections_found == [
        Section.HEADER,
        Section.SUMMARY,
        Section.EXPERIENCE,
        Section.SKILLS,
        Section.EDUCATION,
    ]
    assert all(s.page == 1 for s in doc.spans)
    star_schema = next(s for s in doc.spans if "star schema" in s.text)
    assert star_schema.section is Section.EXPERIENCE


def test_pdf_wrapped_paragraph_is_one_span(dotnet_markup: str) -> None:
    doc = extract_resume(build_pdf(dotnet_markup))
    summary = [s for s in doc.spans if s.section is Section.SUMMARY and s.kind is SpanKind.LINE]
    assert len(summary) == 1
    assert summary[0].text.endswith("for financial services clients.")


def test_pdf_page_numbers_on_long_resume(data_engineer_markup: str) -> None:
    long_markup = (
        data_engineer_markup
        + "\n## Projects\n"
        + "\n".join(
            f"- Project {i} built a reporting pipeline in Python for a fictional client."
            for i in range(60)
        )
    )
    doc = extract_resume(build_pdf(long_markup))
    assert doc.page_count is not None and doc.page_count >= 2
    assert {s.page for s in doc.spans} == set(range(1, doc.page_count + 1))
    assert doc.spans[-1].section is Section.PROJECTS


def test_docx_matches_pdf(data_engineer_markup: str) -> None:
    pdf = extract_resume(build_pdf(data_engineer_markup))
    docx = extract_resume(build_docx(data_engineer_markup, skills_as_table=True))
    assert docx.file_type is FileType.DOCX
    assert docx.page_count is None
    assert [(s.section, s.kind) for s in docx.spans] == [(s.section, s.kind) for s in pdf.spans]


def test_docx_skills_table_rows_stay_in_skills(data_engineer_markup: str) -> None:
    doc = extract_resume(build_docx(data_engineer_markup, skills_as_table=True))
    skills = [s.text for s in doc.spans if s.section is Section.SKILLS and s.kind is SpanKind.LINE]
    assert "Languages: Python, SQL, Scala" in skills
    # "Languages" is also a section name; inside a table it must not start a new section.
    assert Section.OTHER not in doc.sections_found


def test_rejects_text_file() -> None:
    with pytest.raises(ExtractionError) as err:
        extract_resume(b"Just some text pretending to be a resume" * 5)
    assert err.value.code == "unsupported_type"


def test_rejects_legacy_doc() -> None:
    with pytest.raises(ExtractionError) as err:
        extract_resume(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    assert err.value.code == "legacy_doc"


def test_rejects_zip_that_is_not_word() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ExtractionError) as err:
        extract_resume(buffer.getvalue())
    assert err.value.code == "unsupported_type"


def test_rejects_docx_zip_bomb() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "0" * (2 * 1024 * 1024))
    limits = ExtractionLimits(max_docx_uncompressed_bytes=1024 * 1024)
    assert len(buffer.getvalue()) < 50_000  # small on disk, large once unpacked
    with pytest.raises(ExtractionError) as err:
        extract_resume(buffer.getvalue(), limits)
    assert err.value.code == "file_too_large"


def test_rejects_too_many_pages(data_engineer_markup: str) -> None:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "Experience with Python and SQL on many pages.")
    with pytest.raises(ExtractionError) as err:
        extract_resume(doc.tobytes(), ExtractionLimits(max_pdf_pages=2))
    assert err.value.code == "too_many_pages"


def test_rejects_encrypted_pdf() -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Secret resume text that should not be readable.")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(ExtractionError) as err:
        extract_resume(data)
    assert err.value.code == "encrypted"


def test_rejects_pdf_without_text() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0))  # an image-only page
    with pytest.raises(ExtractionError) as err:
        extract_resume(doc.tobytes())
    assert err.value.code == "no_text"


def test_rejects_corrupt_pdf() -> None:
    with pytest.raises(ExtractionError) as err:
        extract_resume(b"%PDF-1.7\nthis is not really a pdf")
    assert err.value.code in {"corrupt_file", "no_text"}


# ---------------------------------------------------------------------------
# v0.5: lines that start a new span
# ---------------------------------------------------------------------------


def _full_width_line(prefix: str = "Environment: Guidewire, Gosu, Angular") -> str:
    """A plain line that runs to the right margin of a builder PDF without wrapping."""
    font, size, width = pymupdf.Font("helv"), PdfStyle().font_size, 612 - 2 * 54
    text, i = prefix, 0
    while font.text_length(f"{text}, Tool{i}", fontsize=size) <= width - 4:
        text, i = f"{text}, Tool{i}", i + 1
    return text


FULL_WIDTH = _full_width_line()


def _lines(data: bytes) -> list[str]:
    return [s.text for s in extract_resume(data).spans]


def test_bold_role_header_after_a_full_width_line_is_its_own_span() -> None:
    markup = f"# Pat Example\n## Experience\n{FULL_WIDTH}\n### Software Engineer, Demo Labs\n"
    lines = _lines(build_pdf(markup))
    assert "Software Engineer, Demo Labs" in lines
    assert not any(line.endswith("Demo Labs") and "Environment" in line for line in lines)


def test_dated_line_after_a_full_width_line_is_its_own_span() -> None:
    # Both lines in the regular font: the date range is what separates them.
    markup = (
        "# Pat Example\n## Experience\n"
        f"{FULL_WIDTH}\nSoftware Engineer, Demo Labs | Jul 2018 - Dec 2019\n"
    )
    lines = _lines(build_pdf(markup))
    assert "Software Engineer, Demo Labs | Jul 2018 - Dec 2019" in lines


def test_wrapped_paragraph_with_a_date_range_mid_sentence_stays_whole() -> None:
    text = (
        "Led the migration of the claims warehouse to a new platform with three teams over "
        "two years, from early planning in 2019 - 2021 through rollout and support"
    )
    lines = _lines(build_pdf(f"# Pat Example\n## Experience\n{text}\n"))
    assert text in lines


def test_short_lines_on_a_sparse_last_page_are_not_joined(data_engineer_markup: str) -> None:
    filler = "\n".join(
        f"- Project {i} built a reporting pipeline in Python for a fictional client."
        for i in range(52)
    )
    markup = (
        f"{data_engineer_markup}\n## Projects\n{filler}\n## Education\n"
        "### M.S. Information Technology, Example University, 2013\n"
        "### B.Tech Electronics, Sample Institute of Technology, 2011\n"
    )
    doc = extract_resume(build_pdf(markup))
    assert doc.page_count == 2
    education = [s.text for s in doc.spans if s.section is Section.EDUCATION]
    assert "M.S. Information Technology, Example University, 2013" in education
    assert "B.Tech Electronics, Sample Institute of Technology, 2011" in education


def test_builder_pdfs_keep_the_en_dash() -> None:
    markup = "# Pat Example\n## Experience\n### Engineer at Example Corp, Mar 2022 \u2013 Present\n"
    assert "Engineer at Example Corp, Mar 2022 \u2013 Present" in _lines(build_pdf(markup))
