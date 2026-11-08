"""Resume structure: roles, their dates, total years and education.

A predicted role matches a gold role when its title and its employer both match
(equal after normalization, or a fuzzy ratio of at least 0.85). Each gold role is
matched to at most one predicted role. Start and end months are then compared on
the matched roles only.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.models import Profile, ResumeDocument, Role, Section, Span
from app.services.structure import RANGE_RE
from evals.dataset import GoldEducation, GoldResume, GoldRole
from evals.matching import align, all_fields_score, normalize_space, normalize_text
from evals.metrics import Rate, mean_absolute_error, pooled, rate_of, rounded

YEARS_TOLERANCE = 0.5
_LEADING_LABEL = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)*:\s")


@dataclass
class MissedItem:
    """A gold role or education entry the app didn't find, and why, as far as the
    extracted lines show."""

    resume: str
    format: str
    gold: dict[str, Any]
    cause: str
    line: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "resume": self.resume,
            "format": self.format,
            "gold": self.gold,
            "cause": self.cause,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass
class ResumeStructure:
    resume: str
    format: str
    gold_roles: int
    predicted_roles: int
    matched_roles: int
    start_correct: int
    end_correct: int
    dates_correct: int
    years_gold: float
    years_predicted: float | None
    education_gold: int
    education_predicted: int
    education_matched: int
    education_year_correct: int
    missed_roles: list[MissedItem] = field(default_factory=list)
    extra_roles: list[dict[str, Any]] = field(default_factory=list)
    date_errors: list[MissedItem] = field(default_factory=list)
    missed_education: list[MissedItem] = field(default_factory=list)
    education_errors: list[MissedItem] = field(default_factory=list)

    @property
    def years_error(self) -> float | None:
        if self.years_predicted is None:
            return None
        return round(self.years_predicted - self.years_gold, 4)


def _role_dict(role: GoldRole | Role) -> dict[str, Any]:
    return {"title": role.title, "employer": role.employer, "start": role.start, "end": role.end}


def _markup_line(markup: str, *parts: str) -> str | None:
    """The markup line holding every part, without its markup prefix."""
    wanted = [normalize_text(p) for p in parts if p]
    for raw in markup.splitlines():
        line = raw.lstrip("#- ").strip()
        if line and all(w in normalize_text(line) for w in wanted):
            return line
    return None


def _span_with(spans: Sequence[Span], *parts: str) -> Span | None:
    wanted = [normalize_text(p) for p in parts if p]
    for span in spans:
        if all(w in normalize_text(span.text) for w in wanted):
            return span
    return None


def _char_changes(source: str, extracted: str) -> list[str]:
    """Characters that differ between the file's line and the extracted line, such
    as "'\u2013' became '\u00b7'"."""
    changes: list[str] = []
    matcher = SequenceMatcher(None, source, extracted, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        change = f"{source[i1:i2]!r} became {extracted[j1:j2]!r}"
        if change not in changes:
            changes.append(change)
    return changes


def _line_difference(source: str | None, extracted: str) -> str | None:
    """Why an extracted line differs from the file's line: "joined" when other text
    was added to it, "changed" when only characters differ, None when they agree."""
    if source is None or normalize_space(source) == normalize_space(extracted):
        return None
    source_words, extracted_words = normalize_text(source), normalize_text(extracted)
    if source_words != extracted_words and source_words in extracted_words:
        return "joined"
    return "changed"


def _diagnose_role(
    gold: GoldRole, gold_resume: GoldResume, document: ResumeDocument, profile: Profile
) -> tuple[str, str | None, str]:
    """(cause, extracted line, detail) for a gold role with no matching prediction."""
    span = _span_with(document.spans, gold.title, gold.employer)
    source = _markup_line(gold_resume.markup, gold.title, gold.employer)
    if span is None:
        return "not_in_text", None, "No extracted line holds both the title and the employer."
    for role in profile.roles:
        if role.header_span_id == span.id:
            return (
                "fields_differ",
                span.text,
                f"Read as a role with title {role.title!r} and employer {role.employer!r}.",
            )
    if span.section is not Section.EXPERIENCE:
        return (
            "outside_section",
            span.text,
            f"The line is in the {span.section.value} section, and roles are only read from "
            "an experience section.",
        )
    difference = _line_difference(source, span.text)
    if difference == "joined":
        return (
            "joined_lines",
            span.text,
            "The header was joined with a neighbouring line during extraction.",
        )
    if RANGE_RE.search(span.text) is None:
        changed = _char_changes(source, span.text) if source and difference else []
        detail = "No date range the app can read is on the line."
        if changed:
            detail += f" Between the file and the extracted text, {', '.join(changed)}."
        return "dates_unreadable", span.text, detail
    detail = "The line was kept as body text, not read as a role."
    if _LEADING_LABEL.match(span.text):
        detail += " It starts with words followed by a colon."
    return "not_a_header", span.text, detail


def _diagnose_dates(
    expected: GoldRole,
    predicted: Role,
    gold_resume: GoldResume,
    document: ResumeDocument,
) -> tuple[str, str | None, str]:
    """(cause, header line, detail) for a matched role whose months are wrong."""
    header = next((s for s in document.spans if s.id == predicted.header_span_id), None)
    line = header.text if header is not None else None
    if predicted.start is not None:
        return (
            "dates_wrong",
            line,
            f"Read {predicted.start} to {predicted.end or 'present'}, labeled "
            f"{expected.start} to {expected.end or 'present'}.",
        )
    detail = "The role was found, but its dates couldn't be read."
    source = _markup_line(gold_resume.markup, expected.title, expected.employer)
    if line is not None and source is not None and _line_difference(source, line):
        changed = _char_changes(source, line)
        if changed:
            detail += f" Between the file and the extracted text, {', '.join(changed)}."
    return "dates_unreadable", line, detail


def _diagnose_education(
    gold: GoldEducation, gold_resume: GoldResume, document: ResumeDocument
) -> tuple[str, str | None, str]:
    span = _span_with(document.spans, gold.degree)
    source = _markup_line(gold_resume.markup, gold.degree)
    if span is None:
        return "not_in_text", None, "No extracted line holds the degree."
    if span.section is not Section.EDUCATION:
        return (
            "outside_section",
            span.text,
            f"The line is in the {span.section.value} section, and education is only read "
            "from an education section.",
        )
    if _line_difference(source, span.text) == "joined":
        return (
            "joined_lines",
            span.text,
            "The entry was joined with a neighbouring line during extraction.",
        )
    return "fields_differ", span.text, "The degree or school was read differently."


def evaluate_resume(
    gold: GoldResume, document: ResumeDocument, profile: Profile, format_name: str
) -> ResumeStructure:
    roles = list(profile.roles)
    alignment = align(
        roles,
        list(gold.roles),
        lambda p, g: all_fields_score([(p.title, g.title), (p.employer, g.employer)]),
    )
    result = ResumeStructure(
        resume=gold.name,
        format=format_name,
        gold_roles=len(gold.roles),
        predicted_roles=len(roles),
        matched_roles=len(alignment.matched),
        start_correct=0,
        end_correct=0,
        dates_correct=0,
        years_gold=gold.total_years,
        years_predicted=profile.total_years,
        education_gold=len(gold.education),
        education_predicted=len(profile.education),
        education_matched=0,
        education_year_correct=0,
    )
    for p_index, g_index, _ in alignment.matched:
        predicted, expected = roles[p_index], gold.roles[g_index]
        start_ok = predicted.start == expected.start
        end_ok = predicted.end == expected.end
        result.start_correct += start_ok
        result.end_correct += end_ok
        result.dates_correct += start_ok and end_ok
        if not (start_ok and end_ok):
            cause, line, detail = _diagnose_dates(expected, predicted, gold, document)
            result.date_errors.append(
                MissedItem(gold.name, format_name, _role_dict(expected), cause, line, detail)
            )
    for g_index in alignment.unmatched_gold:
        expected = gold.roles[g_index]
        cause, line, detail = _diagnose_role(expected, gold, document, profile)
        result.missed_roles.append(
            MissedItem(gold.name, format_name, _role_dict(expected), cause, line, detail)
        )
    for p_index in alignment.unmatched_predicted:
        result.extra_roles.append(
            {"resume": gold.name, "format": format_name, "predicted": _role_dict(roles[p_index])}
        )

    education = list(profile.education)
    edu_alignment = align(
        education,
        list(gold.education),
        lambda p, g: all_fields_score([(p.degree, g.degree), (p.school, g.school)]),
    )
    result.education_matched = len(edu_alignment.matched)
    for p_index, g_index, _ in edu_alignment.matched:
        entry, expected_entry = education[p_index], gold.education[g_index]
        if entry.year == expected_entry.year:
            result.education_year_correct += 1
            continue
        line = next((s.text for s in document.spans if s.id in entry.span_ids), None)
        source = _markup_line(gold.markup, expected_entry.degree)
        joined = line is not None and _line_difference(source, line) == "joined"
        result.education_errors.append(
            MissedItem(
                gold.name,
                format_name,
                {
                    "degree": expected_entry.degree,
                    "school": expected_entry.school,
                    "year": expected_entry.year,
                },
                "joined_lines" if joined else "year_wrong",
                line,
                f"Read the year {entry.year}, labeled {expected_entry.year}.",
            )
        )
    for g_index in edu_alignment.unmatched_gold:
        expected_edu = gold.education[g_index]
        cause, line, detail = _diagnose_education(expected_edu, gold, document)
        result.missed_education.append(
            MissedItem(
                gold.name,
                format_name,
                {
                    "degree": expected_edu.degree,
                    "school": expected_edu.school,
                    "year": expected_edu.year,
                },
                cause,
                line,
                detail,
            )
        )
    return result


def summarize(results: Sequence[ResumeStructure]) -> dict[str, Any]:
    """Metrics over a set of (resume, format) results."""
    matched = sum(r.matched_roles for r in results)
    errors = [r.years_error for r in results if r.years_error is not None]
    return {
        "resumes": len(results),
        "role_precision": Rate(matched, sum(r.predicted_roles for r in results)).to_dict(),
        "role_recall": Rate(matched, sum(r.gold_roles for r in results)).to_dict(),
        "start_month_accuracy": pooled(
            Rate(r.start_correct, r.matched_roles) for r in results
        ).to_dict(),
        "end_month_accuracy": pooled(
            Rate(r.end_correct, r.matched_roles) for r in results
        ).to_dict(),
        "total_years_mae": rounded(mean_absolute_error(errors)),
        "total_years_measured": Rate(len(errors), len(results)).to_dict(),
        "total_years_within_half": rate_of(
            r.years_error is not None and abs(r.years_error) <= YEARS_TOLERANCE + 1e-9
            for r in results
        ).to_dict(),
        "education_recall": pooled(
            Rate(r.education_matched, r.education_gold) for r in results
        ).to_dict(),
        "education_precision": pooled(
            Rate(r.education_matched, r.education_predicted) for r in results
        ).to_dict(),
        "education_year_accuracy": pooled(
            Rate(r.education_year_correct, r.education_matched) for r in results
        ).to_dict(),
    }


def per_resume_rows(results: Sequence[ResumeStructure]) -> list[dict[str, Any]]:
    return [
        {
            "resume": r.resume,
            "format": r.format,
            "roles_gold": r.gold_roles,
            "roles_found": r.predicted_roles,
            "roles_matched": r.matched_roles,
            "dates_correct": r.dates_correct,
            "years_gold": r.years_gold,
            "years_app": r.years_predicted,
            "education_gold": r.education_gold,
            "education_matched": r.education_matched,
        }
        for r in results
    ]
