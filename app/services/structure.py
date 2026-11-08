"""Read structure from a resume: roles with dates, total years of experience,
education and measurable results.

Everything here is rule based and best effort. A date that can't be read becomes
a warning in the profile. It is never guessed, and it never stops the analysis.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.models import Education, Profile, ResumeDocument, Role, Section, Span, SpanKind
from app.services.text import section_for_heading

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_YEAR = r"(?:19|20)\d{2}"
# One date: "Mar 2022", "March 2022", "03/2022", "2022-03" or "2022". The ISO form
# comes before the bare year so "2022-03" isn't read as 2022 followed by junk, and
# its lookahead keeps "2019-2021" a range of two years.
_DATE = (
    rf"{_MONTH_NAME}\.?,?\s+{_YEAR}"
    rf"|(?:0?[1-9]|1[0-2])\s*/\s*{_YEAR}"
    rf"|{_YEAR}-(?:0[1-9]|1[0-2])(?!\d)"
    rf"|{_YEAR}"
)
_END = r"present|current|now|till\s+(?:date|now)|to\s+date|date|today"
_SEPARATOR = r"\s*(?:-|\u2013|\u2014)\s*|\s+(?:to|until|through)\s+"

RANGE_RE = re.compile(
    rf"(?<![\w/])(?P<start>{_DATE})(?:{_SEPARATOR})(?P<end>{_DATE}|{_END})(?![\w/])",
    re.IGNORECASE,
)
_DATE_TOKEN_RE = re.compile(rf"(?<![\w/])(?:{_DATE})(?![\w/])", re.IGNORECASE)
_END_RE = re.compile(rf"(?:{_END})", re.IGNORECASE)
# Anything that looks like a date, used to spot header lines whose dates can't be read.
_DATEISH_RE = re.compile(
    rf"(?<!\w)(?:\d{{1,2}}\s*/\s*)?{_YEAR}(?!\w)|\b{_MONTH_NAME}\b\.?\s*'?\d{{2}}",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(rf"(?<![\w/])({_YEAR})(?!\w)")

_MONTH_DATE_RE = re.compile(rf"({_MONTH_NAME})\.?,?\s+({_YEAR})", re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(rf"(\d{{1,2}})\s*/\s*({_YEAR})")
_ISO_DATE_RE = re.compile(rf"({_YEAR})-(\d{{2}})")


@dataclass(frozen=True)
class _Date:
    year: int
    month: int | None  # None when the resume gives only a year


def _parse_date(token: str) -> _Date:
    token = token.strip()
    if found := _MONTH_DATE_RE.fullmatch(token):
        return _Date(int(found.group(2)), _MONTH_NUMBERS[found.group(1).lower()[:3]])
    if found := _NUMERIC_DATE_RE.fullmatch(token):
        return _Date(int(found.group(2)), int(found.group(1)))
    if found := _ISO_DATE_RE.fullmatch(token):
        return _Date(int(found.group(1)), int(found.group(2)))
    return _Date(int(token), None)


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def _month_text(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _role_interval(role: Role) -> tuple[int, int] | None:
    """First and last month of a role, both counted."""
    if role.start is None or role.months is None:
        return None
    year, month = (int(part) for part in role.start.split("-"))
    start = _month_index(year, month)
    return start, start + role.months - 1


def merged_months(roles: Iterable[Role]) -> int:
    """Months covered by the roles, counting overlapping months once."""
    intervals = sorted(i for role in roles if (i := _role_interval(role)) is not None)
    total = 0
    current: tuple[int, int] | None = None
    for start, end in intervals:
        if current is None or start > current[1] + 1:
            if current is not None:
                total += current[1] - current[0] + 1
            current = (start, end)
        else:
            current = (current[0], max(current[1], end))
    if current is not None:
        total += current[1] - current[0] + 1
    return total


def to_years(months: int) -> float:
    """Months to years, rounded half up to one decimal."""
    years = (Decimal(months) / Decimal(12)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(years)


def experience_roles(profile: Profile) -> list[Role]:
    return [role for role in profile.roles if role.section is Section.EXPERIENCE]


def years_with_spans(profile: Profile, span_ids: set[str]) -> float | None:
    """Years across experience roles whose header or bullets include any of the
    spans. None when no experience role has readable dates."""
    dated = [role for role in experience_roles(profile) if role.months is not None]
    if not dated:
        return None
    hits = [
        role
        for role in dated
        if role.header_span_id in span_ids or span_ids.intersection(role.bullet_span_ids)
    ]
    return to_years(merged_months(hits))


# ---------------------------------------------------------------------------
# Role headers
# ---------------------------------------------------------------------------

_TITLE_WORDS = re.compile(
    r"\b(?:engineer|developer|analyst|scientist|manager|consultant|architect|intern|lead"
    r"|director|specialist|administrator|designer|officer|associate|coordinator|programmer"
    r"|tester|technician|assistant|head|president|vp|founder|co-founder|owner|contractor"
    r"|freelancer|researcher|professor|lecturer|teacher|instructor|accountant|advisor"
    r"|adviser|representative|supervisor|executive|strategist|writer|editor|principal"
    r"|trainee|apprentice|fellow)s?\b",
    re.IGNORECASE,
)
_PIPE_SPLIT = re.compile(r"\s+[|\u2022\u00b7]\s+|\s*\|\s*")
_AT_SPLIT = re.compile(r"\s+(?:at|@)\s+")
_INNER_SPLIT = re.compile(r",\s+|\s+[-\u2013\u2014]\s+")
# "Tech stack: Python, SQL" or "Client: Example Bank" is a body line, never a header.
_LABEL_RE = re.compile(r"^[A-Za-z]+(?: [A-Za-z]+)?:\s")
# Header parts are separated by a comma, pipe, dash or "at". A short line without
# one ("Promoted to team lead in 2021") is body text even if it mentions a year.
_HEADER_SEPARATOR = re.compile(r",\s|\||\s[-\u2013\u2014]\s|\s(?:at|@)\s")
_ABBREVIATION_END = re.compile(r"\b(?:inc|ltd|co|corp|llc|jr|sr|st)\.$", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_EDGE_PUNCTUATION = " |,;:-\u2013\u2014\u2022\u00b7"
_MAX_HEADER_WORDS = 14


def _clean(text: str) -> str:
    text = _EMPTY_BRACKETS.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(_EDGE_PUNCTUATION)


def _is_sentence(text: str) -> bool:
    return text.endswith(".") and not _ABBREVIATION_END.search(text)


def _header_like(text: str) -> bool:
    words = text.split()
    return (
        0 < len(words) <= _MAX_HEADER_WORDS and not _is_sentence(text) and not _LABEL_RE.match(text)
    )


def _order(first: str, second: str) -> tuple[str, str]:
    """Return (title, employer). The part with a job-title word is the title; when
    that doesn't decide it, the title comes first ("Title, Employer")."""
    first, second = _clean(first), _clean(second)
    if _TITLE_WORDS.search(second) and not _TITLE_WORDS.search(first):
        return second, first
    return first, second


def split_title_employer(text: str) -> tuple[str | None, str | None]:
    """Split a header (dates already removed) into title and employer."""
    segments = [_clean(s) for s in _PIPE_SPLIT.split(text)]
    segments = [s for s in segments if s]
    if not segments:
        return None, None
    head = segments[0]
    if len(segments) >= 2 and not (_AT_SPLIT.search(head) or _INNER_SPLIT.search(head)):
        # "Title | Employer | Location"
        return _order(head, segments[1])
    at = _AT_SPLIT.search(head)
    if at:
        return _clean(head[: at.start()]) or None, _clean(head[at.end() :]) or None
    inner = _INNER_SPLIT.search(head)
    if inner:
        title, employer = _order(head[: inner.start()], head[inner.end() :])
        return title or None, employer or None
    return head, None


@dataclass
class _Draft:
    header: Span
    title: str | None
    employer: str | None
    section: Section
    start: _Date | None = None
    end: _Date | None = None
    is_current: bool = False
    date_text: str = ""  # the line the dates came from, quoted in warnings
    body: list[str] = field(default_factory=list)


def _draft(header: Span, text: str, section: Section, found: re.Match[str] | None) -> _Draft:
    title, employer = split_title_employer(text)
    draft = _Draft(header=header, title=title, employer=employer, section=section)
    if found is not None:
        draft.start = _parse_date(found.group("start"))
        end = found.group("end")
        if _END_RE.fullmatch(end):
            draft.is_current = True
        else:
            draft.end = _parse_date(end)
    return draft


def _read_role_drafts(spans: list[Span], section: Section) -> list[_Draft]:
    drafts: list[_Draft] = []
    current: _Draft | None = None
    # A short line with no dates. It is a header if the next line is only dates
    # ("Senior Engineer, Acme" then "Mar 2022 - Present"); otherwise it's body text.
    pending: Span | None = None

    def attach(span: Span | None) -> None:
        if span is not None and current is not None:
            current.body.append(span.id)

    for span in spans:
        if span.kind is SpanKind.HEADING and section_for_heading(span.text) is not None:
            attach(pending)
            pending = None
            current = None
            continue
        if span.kind is SpanKind.BULLET:
            attach(pending)
            pending = None
            attach(span)
            continue

        # A line, or a styled heading that isn't a section name (Word "Heading 2" roles).
        text = span.text
        found = RANGE_RE.search(text)
        if found is not None:
            rest = _clean(f"{text[: found.start()]} {text[found.end() :]}")
            dates_first = not _clean(text[: found.start()])
            if pending is not None and dates_first:
                current = _draft(pending, pending.text, section, found)
                current.date_text = f"{pending.text} {text}"
                current.body.append(span.id)
                drafts.append(current)
                pending = None
                continue
            attach(pending)
            pending = None
            if rest and not _header_like(rest):
                attach(span)  # a sentence that happens to contain dates
                continue
            current = _draft(span, rest, section, found)
            current.date_text = text
            drafts.append(current)
            continue

        attach(pending)
        pending = None
        if not _header_like(text):
            attach(span)
        elif _DATEISH_RE.search(text) and _HEADER_SEPARATOR.search(text):
            # Looks like a header with dates, but they can't be read.
            current = _Draft(header=span, title=None, employer=None, section=section)
            current.title, current.employer = split_title_employer(
                _clean(_DATE_TOKEN_RE.sub(" ", text))
            )
            current.date_text = text
            drafts.append(current)
        else:
            pending = span
    attach(pending)
    return drafts


def _resolve(draft: _Draft, today: date, warnings: list[str]) -> Role:
    def role(start: str | None, end: str | None, months: int | None) -> Role:
        return Role(
            title=draft.title,
            employer=draft.employer,
            section=draft.section,
            start=start,
            end=end,
            is_current=draft.is_current,
            months=months,
            header_span_id=draft.header.id,
            bullet_span_ids=draft.body,
        )

    quoted = f'"{draft.date_text}"'
    if draft.start is None:
        warnings.append(
            f"Couldn't read the dates in {quoted}, so that role isn't counted in years "
            "of experience."
        )
        return role(None, None, None)

    today_index = _month_index(today.year, today.month)
    year_only = draft.start.month is None or (draft.end is not None and draft.end.month is None)
    start_index = _month_index(draft.start.year, draft.start.month or 1)
    end_text: str | None = None
    if draft.end is None:
        end_index = today_index
    else:
        end_index = _month_index(draft.end.year, draft.end.month or 12)
        end_text = _month_text(end_index)
    start_text = _month_text(start_index)

    if start_index > today_index:
        warnings.append(f"The role {quoted} starts after today, so it isn't counted.")
        return role(start_text, end_text, None)
    if end_index < start_index:
        warnings.append(f"The role {quoted} ends before it starts, so it isn't counted.")
        return role(start_text, end_text, None)
    if end_index > today_index:
        if draft.end is not None and draft.end.month is not None:
            warnings.append(f"The role {quoted} ends after today, so it was counted up to now.")
        end_index = today_index
    if year_only:
        warnings.append(
            f"{quoted} gives a year without a month, so January was assumed for a start "
            "year and December for an end year. Add months for a more exact count."
        )
    return role(start_text, end_text, end_index - start_index + 1)


def read_roles(spans: list[Span], section: Section, today: date) -> tuple[list[Role], list[str]]:
    warnings: list[str] = []
    roles = [_resolve(d, today, warnings) for d in _read_role_drafts(spans, section)]
    return roles, warnings


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

_SCHOOL_RE = re.compile(
    r"\b(?:universit(?:y|ies|\u00e9|at)|college|institute|school|academy|polytechnic"
    r"|conservatory)\b",
    re.IGNORECASE,
)
_DEGREE_RE = re.compile(
    r"(?i:\b(?:bachelor|master|doctor(?:ate)?|associate|diploma|certificate|ph\.?\s?d|mba)\b)"
    r"|(?<![\w.])[BM]\.?\s?(?:S|A|Sc|E|Eng|Tech|Com|Ed|Phil)\.?(?!\w)"
    r"|\b(?:BBA|BCA|MCA|BSc|MSc|BTech|MTech|BEng|MEng|LLB|LLM|J\.D\.?)(?!\w)"
)
_EDUCATION_SPLIT = re.compile(r"\s*[|,;\u2022\u00b7]\s*|\s+[-\u2013\u2014]\s+|\s+(?:at|from)\s+")
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


def _education_parts(text: str) -> tuple[str | None, str | None, int | None]:
    years = [int(y) for y in _YEAR_RE.findall(text)]
    cleaned = _DATE_TOKEN_RE.sub(" ", RANGE_RE.sub(" ", text))
    parts = [_clean(p) for p in _EDUCATION_SPLIT.split(cleaned)]
    parts = [p for p in parts if p and not _STATE_CODE.match(p)]
    school = next((p for p in parts if _SCHOOL_RE.search(p)), None)
    degree = next((p for p in parts if p != school and _DEGREE_RE.search(p)), None)
    return degree, school, (years[-1] if years else None)


def read_education(spans: list[Span]) -> list[Education]:
    entries: list[Education] = []
    previous: Span | None = None
    for span in spans:
        if span.kind is SpanKind.HEADING and section_for_heading(span.text) is not None:
            previous = None
            continue
        degree, school, year = _education_parts(span.text)
        last = entries[-1] if entries else None
        follows_last = last is not None and previous is not None and previous.id in last.span_ids
        if last is not None and follows_last:
            # A degree and its school (or year) on consecutive lines are one entry.
            fills_school = school and not degree and last.school is None
            fills_degree = degree and not school and last.degree is None
            fills_year = year and not degree and not school and last.year is None
            if fills_school or fills_degree or fills_year:
                last.school = last.school or school
                last.degree = last.degree or degree
                last.year = last.year or year
                last.span_ids.append(span.id)
                previous = span
                continue
        if degree or school:
            entries.append(Education(degree=degree, school=school, year=year, span_ids=[span.id]))
        previous = span
    return entries


# ---------------------------------------------------------------------------
# Measurable results
# ---------------------------------------------------------------------------

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT = (
    r"(?:milliseconds?|ms|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?"
    r"|years?|yrs?)"
)
_SCALE = r"(?:million|billion|thousand|bn|mm|[kKmMbB])"
_CURRENCY = rf"[$\u20ac\u00a3\u20b9]\s?{_NUM}(?:\s?{_SCALE}\b)?"
_QUANTITY = rf"(?:{_CURRENCY}|{_NUM}(?:\s?%|\s?percent\b|x(?!\w)|\s?\u00d7|\+|\s?{_UNIT}\b)?)"
_START = r"(?<![\w.$\u20ac\u00a3\u20b9/#-])"


def _not_year_range(_: str, found: re.Match[str]) -> bool:
    """ "2019 to 2021" is a date range, not a result."""
    numbers = re.findall(r"\d[\d,.]*", found.group())
    return not all(re.fullmatch(_YEAR, n) for n in numbers)


def _plain_count_ok(text: str, found: re.Match[str]) -> bool:
    """A bare number counts unless it reads like a year or a version ("Python 3",
    "Windows 10"): a capitalized word right before it that isn't the first word."""
    value = found.group()
    if re.fullmatch(rf"{_YEAR}", value):
        return False
    before = text[: found.start()]
    previous = re.search(r"(\S+)\s+$", before)
    if previous is None:
        return True
    is_first_word = not before[: previous.start()].strip()
    return is_first_word or not previous.group(1)[:1].isupper()


_METRIC_PATTERNS: list[tuple[re.Pattern[str], Callable[[str, re.Match[str]], bool] | None]] = [
    # "5 hours to 90 minutes", "35% to 70%", "$2M to $3.5M"
    (
        re.compile(rf"{_START}{_QUANTITY}\s+(?:to|->|\u2192)\s+{_QUANTITY}", re.IGNORECASE),
        _not_year_range,
    ),
    (re.compile(rf"{_START}{_CURRENCY}", re.IGNORECASE), None),
    (re.compile(rf"{_START}{_NUM}\s?(?:%|percent\b)", re.IGNORECASE), None),
    (re.compile(rf"{_START}{_NUM}(?:x|\s?\u00d7)(?!\w)", re.IGNORECASE), None),
    (re.compile(rf"{_START}{_NUM}\s?{_UNIT}\b", re.IGNORECASE), None),
    (re.compile(rf"{_START}{_NUM}\+"), None),
    (
        re.compile(rf"{_START}{_NUM}(?:[KMB]\b|\s(?:million|billion|thousand)\b)?(?![\w%+/-])"),
        _plain_count_ok,
    ),
]


def find_metrics(text: str) -> list[str]:
    """Numbers that describe a result, in reading order."""
    taken: list[tuple[int, int, str]] = []
    for pattern, check in _METRIC_PATTERNS:
        for found in pattern.finditer(text):
            start, end = found.span()
            if any(start < t_end and t_start < end for t_start, t_end, _ in taken):
                continue
            if check is not None and not check(text, found):
                continue
            taken.append((start, end, found.group().strip()))
    return [metric for _, _, metric in sorted(taken)]


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_RESULT_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS}


def parse_profile(resume: ResumeDocument, today: date | None = None) -> Profile:
    """Read roles, years of experience, education and measurable results.

    `today` decides how long current roles have lasted. Tests pass a fixed date.
    """
    today = today or date.today()
    warnings: list[str] = []

    def in_section(section: Section) -> list[Span]:
        return [span for span in resume.spans if span.section is section]

    roles, role_warnings = read_roles(in_section(Section.EXPERIENCE), Section.EXPERIENCE, today)
    warnings.extend(role_warnings)
    project_roles, project_warnings = read_roles(
        in_section(Section.PROJECTS), Section.PROJECTS, today
    )
    # Projects only count as dated roles when the section has dated headers.
    if any(role.start is not None for role in project_roles):
        roles.extend(project_roles)
        warnings.extend(project_warnings)

    dated = [
        role for role in roles if role.section is Section.EXPERIENCE and role.months is not None
    ]
    total_years = to_years(merged_months(dated)) if dated else None
    if Section.EXPERIENCE not in resume.sections_found:
        warnings.append("No experience section was found, so no roles or dates were read.")
    elif total_years is None:
        warnings.append(
            "No role dates could be read in the experience section, so years of experience "
            "weren't calculated. A line such as \"Data Engineer, Example Corp | Mar 2022 - "
            'Present" works best.'
        )

    has_headings = any(span.kind is SpanKind.HEADING for span in resume.spans)
    metrics: dict[str, list[str]] = {}
    for span in resume.spans:
        if span.kind is not SpanKind.BULLET:
            continue
        if has_headings and span.section not in _RESULT_SECTIONS:
            continue
        found = find_metrics(span.text)
        if found:
            metrics[span.id] = found

    return Profile(
        roles=roles,
        total_years=total_years,
        education=read_education(in_section(Section.EDUCATION)),
        metric_bullets=list(metrics),
        metrics=metrics,
        warnings=warnings,
    )
