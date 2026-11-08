"""Document quality: does the Word export read back the same, and is it a plain,
single-column file?

For every resume in every format, the app's own export (build_docx, with no
corrections or rewrites) is read back with the app's own extractor and pipeline.
The round trip counts as unchanged when the sections of every line, the roles
(title, employer, start and end), the total years and, for every pair that uses the
resume, each requirement's status are the same as when the original file was read.

The structural check opens the exported file itself: no tables, text boxes,
images, headers or footers, one column, section headings in Word's Heading 1 style,
bullets in its List Bullet style, and English (en-US) as the language.
"""

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from docx import Document

from app.models import ResumeDocument, Role, SpanKind
from app.services.analysis import analyze
from app.services.export import LANGUAGE, build_docx
from app.services.extraction import extract_resume
from app.services.skills import SkillCatalog
from app.services.structure import parse_profile
from app.services.text import section_for_heading
from evals.dataset import Dataset
from evals.formats import Format
from evals.metrics import rate_of
from evals.pipeline import PairRun, Renderer

STRUCTURE_CHECKS = (
    "no_tables",
    "no_text_boxes",
    "no_images",
    "no_headers_or_footers",
    "one_column",
    "heading_styles",
    "list_styles",
    "language",
)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TEXT_BOX = re.compile(r"txbxContent|<v:textbox|<wps:txbx|<w:txbx", re.IGNORECASE)
_IMAGE = re.compile(r"<w:drawing|<w:pict|<v:imagedata|<pic:pic", re.IGNORECASE)
_HEADER_FOOTER = re.compile(r"w:headerReference|w:footerReference")


@dataclass
class FileQuality:
    """One resume in one format, exported and read back."""

    resume: str
    format: str
    sections: bool
    roles: bool
    total_years: bool
    structure: dict[str, bool]
    differences: list[str] = field(default_factory=list)
    has_headings: bool = True

    @property
    def structure_ok(self) -> bool:
        return all(self.structure.values())


@dataclass
class PairQuality:
    pair: str
    resume: str
    format: str
    statuses: bool
    differences: list[str] = field(default_factory=list)


def _role(role: Role) -> tuple[str | None, str | None, str | None, str | None]:
    return role.title, role.employer, role.start, role.end


def _style(paragraph: Any) -> str | None:
    style = paragraph.style
    return None if style is None else str(style.name)


def structure_checks(data: bytes, source: ResumeDocument) -> dict[str, bool]:
    """The structural checks on an exported file, with `source` the lines it came from."""
    doc = Document(io.BytesIO(data))
    body = doc.element.xml
    parts = list(doc.part.package.iter_parts())
    content_types = [part.content_type for part in parts]
    section_headings = [
        s for s in source.spans if s.kind is SpanKind.HEADING and section_for_heading(s.text)
    ]
    heading_paragraphs = [p for p in doc.paragraphs if _style(p) == "Heading 1"]
    bullets = [s for s in source.spans if s.kind is SpanKind.BULLET]
    list_paragraphs = [p for p in doc.paragraphs if _style(p) == "List Bullet"]
    columns = [
        cols.get(f"{_W}num")
        for section in doc.sections
        for cols in section._sectPr.iter(f"{_W}cols")
    ]
    lang = doc.styles.element.find(f"{_W}docDefaults/{_W}rPrDefault/{_W}rPr/{_W}lang")
    return {
        "no_tables": not doc.tables,
        "no_text_boxes": not _TEXT_BOX.search(body),
        "no_images": not _IMAGE.search(body)
        and not any(ct.startswith("image/") for ct in content_types),
        "no_headers_or_footers": not _HEADER_FOOTER.search(body)
        and not any("header" in ct or "footer" in ct for ct in content_types),
        "one_column": all(num in (None, "1") for num in columns),
        # A resume with no section headings gets none in the export either: the
        # export never adds a line. Those files are counted apart.
        "heading_styles": len(heading_paragraphs) == len(section_headings),
        "list_styles": len(list_paragraphs) == len(bullets),
        "language": lang is not None
        and lang.get(f"{_W}val") == LANGUAGE
        and doc.core_properties.language == LANGUAGE,
    }


class Exporter:
    """Exports each (format, resume) once and keeps the bytes."""

    def __init__(self, dataset: Dataset, renderer: Renderer) -> None:
        self.dataset = dataset
        self.renderer = renderer
        self._files: dict[tuple[str, str], tuple[ResumeDocument, bytes]] = {}

    def export(self, fmt: Format, resume: str) -> tuple[ResumeDocument, bytes]:
        key = (fmt.name, resume)
        if key not in self._files:
            document = extract_resume(self.renderer.file(fmt, resume))
            profile = parse_profile(document, today=self.dataset.resumes[resume].as_of)
            data = build_docx(
                document, {}, {}, role_header_ids={r.header_span_id for r in profile.roles}
            )
            self._files[key] = (document, data)
        return self._files[key]


def check_files(
    dataset: Dataset, formats: Sequence[Format], exporter: Exporter
) -> list[FileQuality]:
    results: list[FileQuality] = []
    for fmt in formats:
        for name, gold in dataset.resumes.items():
            original, data = exporter.export(fmt, name)
            before = parse_profile(original, today=gold.as_of)
            again = extract_resume(data)
            after = parse_profile(again, today=gold.as_of)
            sections = [s.section for s in original.spans] == [s.section for s in again.spans]
            roles = [_role(r) for r in before.roles] == [_role(r) for r in after.roles]
            years = before.total_years == after.total_years
            differences: list[str] = []
            if not sections:
                differences.append(
                    f"sections: {len(original.spans)} lines read first, {len(again.spans)} "
                    "read back, or a line moved to another section"
                )
            if not roles:
                differences.append(
                    f"roles: {[_role(r) for r in before.roles]} became "
                    f"{[_role(r) for r in after.roles]}"
                )
            if not years:
                differences.append(f"total years: {before.total_years} became {after.total_years}")
            structure = structure_checks(data, original)
            differences += [f"structure: {k} failed" for k, ok in structure.items() if not ok]
            has_headings = any(
                s.kind is SpanKind.HEADING and section_for_heading(s.text) for s in original.spans
            )
            results.append(
                FileQuality(
                    name, fmt.name, sections, roles, years, structure, differences, has_headings
                )
            )
    return results


def check_pairs(
    dataset: Dataset,
    formats: Sequence[Format],
    exporter: Exporter,
    runs: Sequence[PairRun],
    catalog: SkillCatalog,
    today: date | None = None,
) -> list[PairQuality]:
    """Each pair's statuses after the round trip, against the original run."""
    by_format = {fmt.name: fmt for fmt in formats}
    results: list[PairQuality] = []
    for run in runs:
        fmt = by_format[run.format]
        _, data = exporter.export(fmt, run.pair.resume)
        _, report = analyze(
            data,
            dataset.jobs[run.pair.job].text,
            catalog=catalog,
            today=today or dataset.resumes[run.pair.resume].as_of,
        )
        before = [(m.requirement.text, m.status.value) for m in run.report.matches]
        after = [(m.requirement.text, m.status.value) for m in report.matches]
        differences = [
            f'"{text}": {status} became {new}'
            for (text, status), (_, new) in zip(before, after, strict=False)
            if status != new
        ]
        if len(before) != len(after):
            differences.append(f"{len(before)} requirements became {len(after)}")
        results.append(
            PairQuality(run.pair.key, run.pair.resume, run.format, before == after, differences)
        )
    return results


def _summary(files: Sequence[FileQuality], pairs: Sequence[PairQuality]) -> dict[str, Any]:
    pairs_by_file: dict[tuple[str, str], list[PairQuality]] = {}
    for pair in pairs:
        pairs_by_file.setdefault((pair.resume, pair.format), []).append(pair)

    def unchanged(file: FileQuality) -> bool:
        statuses = all(p.statuses for p in pairs_by_file.get((file.resume, file.format), []))
        return file.sections and file.roles and file.total_years and statuses

    return {
        "files": len(files),
        "pairs": len(pairs),
        "sections_unchanged": rate_of(f.sections for f in files).to_dict(),
        "roles_unchanged": rate_of(f.roles for f in files).to_dict(),
        "total_years_unchanged": rate_of(f.total_years for f in files).to_dict(),
        "statuses_unchanged": rate_of(p.statuses for p in pairs).to_dict(),
        "round_trip_unchanged": rate_of(unchanged(f) for f in files).to_dict(),
        "structure_ok": rate_of(f.structure_ok for f in files).to_dict(),
        "without_section_headings": sum(not f.has_headings for f in files),
        "structure_checks": {
            check: rate_of(f.structure[check] for f in files).to_dict()
            for check in STRUCTURE_CHECKS
        },
    }


def summarize(
    formats: Sequence[Format], files: Sequence[FileQuality], pairs: Sequence[PairQuality]
) -> dict[str, Any]:
    return {
        "overall": _summary(files, pairs),
        "by_format": {
            fmt.name: _summary(
                [f for f in files if f.format == fmt.name],
                [p for p in pairs if p.format == fmt.name],
            )
            for fmt in formats
        },
    }


def failures(files: Sequence[FileQuality], pairs: Sequence[PairQuality]) -> list[dict[str, Any]]:
    """Every file or pair whose round trip changed something, with what changed."""
    out: list[dict[str, Any]] = [
        {"resume": f.resume, "format": f.format, "differences": f.differences}
        for f in files
        if f.differences
    ]
    out += [
        {"pair": p.pair, "format": p.format, "differences": p.differences}
        for p in pairs
        if p.differences
    ]
    return out
