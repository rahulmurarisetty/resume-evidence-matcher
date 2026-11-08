"""Rule-based job-description parser.

Splits a pasted job description into requirements and labels each one required,
preferred or context (responsibilities and background). v0.3 adds a Claude-based
parser behind the same interface; this one stays as the fallback and the baseline
it is measured against.
"""

import re

from app.models import JobDescription, MatchMode, Priority, Requirement, Seniority
from app.services.skills import SkillCatalog
from app.services.text import BULLET_ONLY_RE, normalize, strip_bullet

# Heading keywords, checked in this order. Preferred comes first so "Preferred
# Qualifications" isn't read as required, and skip comes before required so
# "About the company" isn't read as context.
_PREFERRED_HEADING = re.compile(
    r"preferred|nice[\s-]to[\s-]have|bonus|desired|desirable|good[\s-]to[\s-]have|pluses|\ba plus\b"
)
_SKIP_HEADING = re.compile(
    r"who we are|benefits|perks|compensation|salary|pay range"
    r"|equal opportunity|\beeo\b|our values|why join|why you'll love|how to apply|location"
    r"|work environment|physical demands"
)
_REQUIRED_HEADING = re.compile(
    r"requirement|qualification|must[\s-]have|\bmust\b|you have|you'll need|you will need"
    r"|what you need|looking for|who you are|what you bring|required|skills|experience|competenc"
)
_CONTEXT_HEADING = re.compile(
    r"responsibilit|what you'll do|what you will do|the role|your role|role overview|duties"
    r"|day[\s-]to[\s-]day|job description|overview|the job|position summary|summary|impact"
)

_LINE_PREFERRED = re.compile(
    r"\b(preferred|nice[\s-]to[\s-]have|a plus|is a plus|are a plus|bonus|desirable|desired"
    r"|good[\s-]to[\s-]have|ideally|familiarity with)\b",
    re.IGNORECASE,
)
_LINE_REQUIRED = re.compile(
    r"\b(must|required|requirement|mandatory|minimum|at least|proven|strong)\b", re.IGNORECASE
)

_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|\u2013|to)\s*\d{1,2}\s*\+?\s*)?(?:years|yrs)\b", re.IGNORECASE
)
_ANY_OF = re.compile(r"\b(or|either)\b", re.IGNORECASE)
_TITLE_PREFIX = re.compile(r"^(job title|title|position|role)\s*:\s*(.+)$", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

_SENIORITY_RULES: list[tuple[re.Pattern[str], Seniority]] = [
    (re.compile(r"\bintern(ship)?\b", re.IGNORECASE), Seniority.INTERN),
    (
        re.compile(r"\b(junior|jr\.?|entry[\s-]level|associate|graduate)\b", re.IGNORECASE),
        Seniority.JUNIOR,
    ),
    (
        re.compile(r"\b(lead|principal|staff|architect|head of|manager)\b", re.IGNORECASE),
        Seniority.LEAD,
    ),
    (re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE), Seniority.SENIOR),
]

_MAX_HEADING_WORDS = 8


def _heading_priority(line: str, catalog: SkillCatalog) -> Priority | str | None:
    """Return a Priority for a section heading, "skip" for sections to ignore, or
    None if the line isn't a heading."""
    text = line.strip()
    if not text or text.endswith((".", ",", ";")):
        return None
    # Bullets are items, never headings ("- Excellent communication skills").
    if strip_bullet(text)[1]:
        return None
    if len(text.rstrip(":").split()) > _MAX_HEADING_WORDS or _YEARS.search(text):
        return None
    # A line naming a real skill is a requirement, not a heading ("Python experience").
    if catalog.skills_in(text):
        return None
    key = text.rstrip(":").strip().lower()
    if _PREFERRED_HEADING.search(key):
        return Priority.PREFERRED
    if key.startswith("about"):
        # "About the role" describes the job, "About you" lists requirements,
        # anything else ("About Acme", "About us") is company background.
        if re.search(r"\b(role|job|position|opportunity)\b", key):
            return Priority.CONTEXT
        if re.search(r"\byou\b", key):
            return Priority.REQUIRED
        return "skip"
    if _SKIP_HEADING.search(key):
        return "skip"
    if _REQUIRED_HEADING.search(key):
        return Priority.REQUIRED
    if _CONTEXT_HEADING.search(key):
        return Priority.CONTEXT
    return None


def _line_priority(text: str, section: Priority) -> Priority:
    if _LINE_PREFERRED.search(text):
        return Priority.PREFERRED
    if section is Priority.CONTEXT and _LINE_REQUIRED.search(text):
        return Priority.REQUIRED
    return section


def _min_years(text: str) -> int | None:
    match = _YEARS.search(text)
    return int(match.group(1)) if match else None


def _seniority(title: str | None, min_years: int | None) -> Seniority:
    if title:
        for pattern, level in _SENIORITY_RULES:
            if pattern.search(title):
                return level
    if min_years is None:
        return Seniority.UNKNOWN
    if min_years >= 8:
        return Seniority.LEAD
    if min_years >= 5:
        return Seniority.SENIOR
    if min_years >= 2:
        return Seniority.MID
    return Seniority.JUNIOR


def _items(lines: list[str]) -> list[str]:
    """Bullets stay whole; long prose lines are split into sentences."""
    items: list[str] = []
    for line in lines:
        text, is_bullet = strip_bullet(line)
        if not text:
            continue
        if is_bullet or len(text) < 200:
            items.append(text)
        else:
            items.extend(s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip())
    return items


def parse_job_description(raw: str, catalog: SkillCatalog) -> JobDescription:
    lines = [normalize(line) for line in raw.splitlines()]
    lines = [line for line in lines if line and not BULLET_ONLY_RE.match(line)]

    title: str | None = None
    # Before the first heading we only keep lines that read like requirements.
    section: Priority | str = "preamble"
    grouped: list[tuple[Priority, str]] = []

    for line in lines:
        prefixed = _TITLE_PREFIX.match(line)
        if prefixed and title is None:
            title = prefixed.group(2).strip()
            continue

        heading = _heading_priority(line, catalog)
        if heading is not None:
            section = heading
            continue

        if section == "skip":
            continue
        if section == "preamble":
            text, is_bullet = strip_bullet(line)
            if title is None and not is_bullet and len(text.split()) <= 12 and "." not in text:
                title = text
                continue
            # Company intros are skipped unless they name a skill or a years requirement.
            if not (catalog.skills_in(text) or _min_years(text)):
                continue
            for item in _items([line]):
                grouped.append((_line_priority(item, Priority.CONTEXT), item))
            continue

        assert isinstance(section, Priority)
        for item in _items([line]):
            grouped.append((_line_priority(item, section), item))

    requirements: list[Requirement] = []
    seen: set[str] = set()
    for priority, text in grouped:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        requirements.append(
            Requirement(
                id=f"r{len(requirements)}",
                text=text,
                priority=priority,
                skills=catalog.skills_in(text),
                match_mode=MatchMode.ANY if _ANY_OF.search(text) else MatchMode.ALL,
                min_years=_min_years(text),
            )
        )

    required_years = [
        r.min_years for r in requirements if r.priority is Priority.REQUIRED and r.min_years
    ]
    any_years = [r.min_years for r in requirements if r.min_years]
    job_years = required_years[0] if required_years else (any_years[0] if any_years else None)

    return JobDescription(
        title=title,
        seniority=_seniority(title, job_years),
        min_years=job_years,
        requirements=requirements,
    )
