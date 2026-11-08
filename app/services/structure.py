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
    r"|trainee|apprentice|fellow|partner|clerk|nurse|attorney|paralegal|underwriter"
    r"|adjuster|agent|auditor|actuary|recruiter|planner|steward|operator)s?\b",
    re.IGNORECASE,
)
_PIPE_SPLIT = re.compile(r"\s+[|\u2022\u00b7]\s+|\s*\|\s*")
_AT_SPLIT = re.compile(r"\s+(?:at|@)\s+")
# A comma, a hyphen with spaces around it, or an en or em dash with or without them
# ("Example Corp\u2014Data Analyst").
_INNER_SPLIT = re.compile(r",\s+|\s+-\s+|\s*[\u2013\u2014]\s*")
# "Tech stack: Python, SQL" or "Client: Example Bank" starts with a label.
_LABEL_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z&.'/ -]{0,40}?)\s*:\s+(?P<value>.*)$")
# Labels whose line is part of a role but never its title or employer.
_BODY_LABELS = re.compile(
    r"^(?:environment|tech(?:nology|nologies)?(?: stack| used)?|stack|tools?(?: used)?"
    r"|software|frameworks?|languages?|databases?|platforms?|skills?(?: used)?|key skills"
    r"|projects?|key projects?|project name|responsibilit(?:y|ies)|duties"
    r"|achievements?|key achievements?|accomplishments?|highlights?|summary|description"
    r"|domain|industry|team(?: size)?|location|note|notes|link|url|github|website"
    r"|portfolio|reference|reason for leaving|reporting to|reports to|scope|impact"
    r"|results?|awards?|methodology|os|operating systems?)$",
    re.IGNORECASE,
)
# Labels that name the employer or the title ("Company: Example Corp", "Role: Developer").
_EMPLOYER_LABELS = re.compile(r"^(?:company|employer|organi[sz]ation|firm)$", re.IGNORECASE)
# Labels that name a consultant's client ("Client: Example Bank"). A client is never
# the title or the employer: the employer is the firm that employs the person.
_CLIENT_LABELS = re.compile(r"^(?:client|end client|customer|account)$", re.IGNORECASE)
_TITLE_LABELS = re.compile(
    r"^(?:role|title|job title|position|designation|job role)$", re.IGNORECASE
)
# Labels that come before the dates ("Duration: Mar 2020 - Present").
_DATE_LABELS = re.compile(r"^(?:duration|dates?|period|tenure|from)$", re.IGNORECASE)
# Header parts are separated by a comma, pipe, dash or "at". A short line without
# one ("Promoted to team lead in 2021") is body text even if it mentions a year.
_HEADER_SEPARATOR = re.compile(r",\s|\||\s[-\u2013\u2014]\s|\s(?:at|@)\s|[\u2013\u2014]")
_ABBREVIATION_END = re.compile(r"\b(?:inc|ltd|co|corp|llc|jr|sr|st)\.$", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"\(\s*\)|\[\s*\]")
_EDGE_PUNCTUATION = " |,;:-\u2013\u2014\u2022\u00b7"
_MAX_HEADER_WORDS = 14
_CONTACT_RE = re.compile(
    r"@|https?://|www\.|linkedin|github\.com|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", re.IGNORECASE
)

# ---- Locations ("Jacksonville, FL", "Remote") that sit next to the employer ----


def _names(text: str, lower: bool = True) -> frozenset[str]:
    names = (name.strip() for name in text.split("|"))
    return frozenset(name.lower() if lower else name for name in names)


_US_STATES = _names(
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV"
    "|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC|PR"
    "|ON|BC|AB|QC|MB|NS|NB|SK|NL|PE",
    lower=False,
)
_STATE_NAMES = _names(
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida"
    "|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine"
    "|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska"
    "|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota"
    "|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota"
    "|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
    "|District of Columbia|Puerto Rico|Ontario|British Columbia|Alberta|Quebec"
    "|Telangana|Andhra Pradesh|Karnataka|Maharashtra|Tamil Nadu|Kerala|Gujarat|Delhi"
    "|Uttar Pradesh|West Bengal|Haryana|Punjab|Rajasthan|Madhya Pradesh|Odisha|Goa"
)
_COUNTRIES = _names(
    "USA|U.S.A|US|U.S|United States|United States of America|India|Canada|UK|U.K"
    "|United Kingdom|England|Scotland|Ireland|Germany|France|Netherlands|Spain|Italy"
    "|Poland|Portugal|Sweden|Switzerland|Australia|New Zealand|Singapore|Philippines"
    "|Malaysia|Mexico|Brazil|Argentina|Colombia|UAE|United Arab Emirates|Saudi Arabia"
    "|Qatar|South Africa|Nigeria|Kenya|Egypt|Japan|China|Hong Kong|Israel"
)
_WORK_MODES = {
    "remote", "hybrid", "onsite", "on-site", "on site", "in-office", "in office",
    "work from home", "wfh", "fully remote", "remote-first",
}  # fmt: skip
# Words that make a name an organization rather than a city.
_ORGANIZATION_WORDS = re.compile(
    r"\b(?:inc|llc|llp|ltd|plc|corp|corporation|co|company|group|bank|insurance|mutual"
    r"|labs?|systems?|solutions?|technolog(?:y|ies)|tech|services?|partners?|holdings?"
    r"|universit(?:y|ies)|college|institute|school|academy|agency|media|health|healthcare"
    r"|software|studios?|consulting|consultants|analytics|logistics|financial|finance"
    r"|capital|networks?|digital|global|international|industries|enterprises?|associates"
    r"|foundation|hospital|clinic|bureau|department|council|authority|platforms?|cloud"
    r"|data|pharma\w*|motors|airlines?|energy|retail|foods?|brands?|ventures|works"
    r"|federal|credit|union|trust|fund|markets?|commerce|freight|express|communications"
    r"|telecom|interactive|games|entertainment|records|press|publishing|news|network"
    r"|government|county|city of|state of|district|army|navy|air force|marines)\b",
    re.IGNORECASE,
)
_PLACE_SEPARATOR = re.compile(r"(\s*,\s*|\s+-\s+|\s*[\u2013\u2014/]\s*|\s+(?:at|@)\s+)")

# Company suffixes. A name that ends with one is an employer, never a title. The
# legal forms (and Infotech, Softech) never end a job title. The descriptive ones
# ("Solutions", "Systems") can ("Director of IT Systems"), so they count only in a
# name with no job-title word.
_LEGAL_SUFFIX = re.compile(
    r"(?:\b(?:pvt|private)\.?\s*(?:ltd|limited)|\b(?:ltd|limited|inc|llc|llp|corp|corporation"
    r"|gmbh|infotech|softech))\.?$",
    re.IGNORECASE,
)
_DESCRIPTIVE_SUFFIX = re.compile(
    r"\b(?:technologies|solutions|consulting|services|systems)\.?$", re.IGNORECASE
)


def is_company(text: str) -> bool:
    """Ends with a company suffix: "Demo Infotech Pvt. Ltd.", "Example Systems"."""
    name = text.strip(" ,;:()|")
    if _LEGAL_SUFFIX.search(name):
        return True
    return bool(_DESCRIPTIVE_SUFFIX.search(name)) and not _TITLE_WORDS.search(name)


def _is_region(part: str) -> bool:
    """A state, province, country or work mode on its own ("FL", "Texas", "Remote")."""
    part = part.strip(" ()")
    lower = part.lower().rstrip(".")
    return (
        part in _US_STATES or lower in _STATE_NAMES or lower in _COUNTRIES or lower in _WORK_MODES
    )


def _is_city(part: str) -> bool:
    """One to three capitalized words that don't name an organization or a job."""
    words = part.strip(" ()").split()
    return (
        0 < len(words) <= 3
        and all(w[:1].isupper() and not any(c.isdigit() for c in w) for w in words)
        and not _ORGANIZATION_WORDS.search(part)
        and not _TITLE_WORDS.search(part)
    )


def _city_after_company(before: str, part: str) -> bool:
    """A lone city right after a name with a company suffix: "Hyderabad" in "Demo
    Infotech Pvt. Ltd, Hyderabad"."""
    return is_company(before) and _is_city(part)


def _place_parts(text: str) -> list[str]:
    """The text's parts with parentheses opened up: "Remote (US)" is two parts."""
    text = re.sub(r"[()]", ",", text)
    return [p.strip() for p in _PLACE_SEPARATOR.split(text)[::2] if p.strip(" ,")]


def _is_location(text: str) -> bool:
    """Only a place or a work mode: "Tampa, FL", "Remote (US)", "Hyderabad, India".
    "Accenture, Chicago, IL" isn't one: a place has at most one city."""
    parts = _place_parts(text)
    if not parts or not any(_is_region(p) for p in parts):
        return False
    cities = [p for p in parts if not _is_region(p)]
    if len(cities) <= 1 and all(_is_city(p) for p in cities):
        return True
    # "Tampa FL", "New York NY"
    words = text.strip(" ()").split()
    return (
        len(parts) == 1
        and len(words) >= 2
        and _is_region(words[-1])
        and _is_city(" ".join(words[:-1]))
    )


def strip_location(text: str) -> str:
    """Remove a place or work mode at the end: "Example Mutual, Jacksonville, FL"
    becomes "Example Mutual", "Example Corp (Remote)" becomes "Example Corp".

    A city is removed only together with the state after it, and only when enough of
    the text is left: in "Data Engineer, Example Corp, Washington" the state is
    removed and the employer kept. A text that is only a place is left as it is.
    """
    text = _clean(text)
    if _is_location(text):
        return text
    while (found := re.search(r"\s*\(([^()]*)\)\s*$", text)) is not None and found.start():
        if not _is_location(found.group(1)):
            break
        text = _clean(text[: found.start()])
    pieces = _PLACE_SEPARATOR.split(text)
    parts, separators = pieces[::2], pieces[1::2]
    # Keep a title and an employer when the text names a job, else one part.
    keep = 2 if _TITLE_WORDS.search(text) else 1

    def drop_last() -> None:
        parts.pop()
        separators.pop()

    state_dropped = False
    while len(parts) > keep and _is_region(parts[-1]):
        state_dropped = state_dropped or parts[-1].strip(" .").lower() not in _WORK_MODES
        drop_last()
    if state_dropped and len(parts) > keep and _is_city(parts[-1]):
        drop_last()
    elif len(parts) > keep and _is_location(parts[-1]):
        drop_last()  # "Example Corp - Tampa FL"
    elif len(parts) > keep and len(parts) >= 2 and _city_after_company(parts[-2], parts[-1]):
        drop_last()  # "Demo Infotech Pvt. Ltd, Hyderabad"
    rebuilt = parts[0]
    for separator, part in zip(separators, parts[1:], strict=True):
        rebuilt += separator + part
    return _clean(rebuilt)


# ---- Splitting a header into title and employer ----


def _clean(text: str) -> str:
    text = _EMPTY_BRACKETS.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(_EDGE_PUNCTUATION)


def _is_sentence(text: str) -> bool:
    return text.endswith(".") and not _ABBREVIATION_END.search(text)


def _label(text: str) -> tuple[str, str] | None:
    """("client", "Example Bank") for "Client: Example Bank", None without a label."""
    found = _LABEL_RE.match(text)
    if found is None:
        return None
    return found.group("label").strip(), found.group("value").strip()


def _label_kind(text: str) -> str | None:
    """How a labeled line reads: "employer", "client" ("Client: Example Bank"),
    "title", "dates", "header" ("Demo Logistics: Senior Engineer") or "body"
    ("Environment: Java, Spring"). None when the line has no label."""
    labeled = _label(text)
    if labeled is None:
        return None
    label, value = labeled
    if _CLIENT_LABELS.match(label):
        return "client"
    if _EMPLOYER_LABELS.match(label):
        return "employer"
    if _TITLE_LABELS.match(label):
        return "title"
    if _DATE_LABELS.match(label):
        return "dates"
    if _BODY_LABELS.match(label) or len(label.split()) > 4:
        return "body"
    # "Employer: Title" when one side reads as a job title.
    if _TITLE_WORDS.search(value) or _TITLE_WORDS.search(label):
        return "header"
    return "body"


def _header_like(text: str) -> bool:
    words = text.split()
    if not (0 < len(words) <= _MAX_HEADER_WORDS) or _is_sentence(text):
        return False
    return _label_kind(text) in (None, "employer", "client", "title", "header", "dates")


_SMALL_WORDS = {"of", "and", "the", "for", "&", "at", "in", "de", "la", "on", "to", "a", "an"}


def _name_like(text: str) -> bool:
    """Reads like a title or an employer: mostly capitalized words ("Example Mutual",
    "Senior Data Engineer"), or a job-title word with at least half of them
    capitalized ("Head of data"). Body text ("Built dashboards in Tableau") isn't."""
    if _CONTACT_RE.search(text):
        return False
    words = [w for w in re.findall(r"[A-Za-z][\w.&'\u2019+#-]*", text)]
    content = [w for w in words if w.lower() not in _SMALL_WORDS]
    if not content or not content[0][0].isupper():
        return False
    share = sum(1 for w in content if w[0].isupper()) / len(content)
    return share >= 0.75 or (share >= 0.5 and bool(_TITLE_WORDS.search(text)))


def _order(first: str, second: str) -> tuple[str, str]:
    """Return (title, employer). A part with a company suffix is the employer, then
    the part with a job-title word is the title; when neither decides it, the title
    comes first ("Title, Employer")."""
    first, second = _clean(first), _clean(second)
    if is_company(first) != is_company(second):
        return (second, first) if is_company(first) else (first, second)
    if _TITLE_WORDS.search(second) and not _TITLE_WORDS.search(first):
        return second, first
    return first, second


def _without_locations(text: str) -> str:
    """Drop place segments ("Tampa, FL") between pipes and a place at the end of each.
    A lone city right after a company name ("Demo Infotech Ltd | Pune") is a place too."""
    segments = [s for s in _PIPE_SPLIT.split(text) if s.strip()]
    kept: list[str] = []
    for segment in segments:
        if _is_location(segment) or (kept and _city_after_company(kept[-1], segment)):
            continue
        kept.append(strip_location(segment))
    return " | ".join(s for s in kept if s)


def client_of(text: str) -> str | None:
    """The client named on a "Client: Example Bank (USA)" line, without the place."""
    labeled = _label(text)
    if labeled is None or not _CLIENT_LABELS.match(labeled[0]):
        return None
    return _without_locations(labeled[1]) or None


_DASH_SPLIT = re.compile(r"\s+-\s+|\s*[\u2013\u2014]\s*")
_COMMA_SPLIT = re.compile(r",\s+")


def split_title_employer(text: str) -> tuple[str | None, str | None]:
    """Split a header (dates already removed) into title and employer."""
    labeled = _label(text)
    if labeled is not None:
        kind = _label_kind(text)
        label, value = labeled
        value = _without_locations(value)
        if kind == "client":
            return None, None  # see client_of()
        if kind == "employer":
            return None, value or None
        if kind == "title":
            return value or None, None
        if kind == "header":
            # "Demo Logistics: Senior Software Engineer"
            title, employer = _order(label, value)
            return title or None, employer or None
    text = _without_locations(text)
    segments = [_clean(s) for s in _PIPE_SPLIT.split(text)]
    segments = [s for s in segments if s]
    if not segments:
        return None, None
    head = segments[0]
    inner = _AT_SPLIT.search(head) or _DASH_SPLIT.search(head) or _COMMA_SPLIT.search(head)
    if len(segments) >= 2 and inner is None:
        # "Title | Employer | Location"
        return _order(head, segments[1])
    if inner is None:
        # One name alone: an employer when it has a company suffix, else a title.
        return (None, head) if is_company(head) else (head, None)
    first, second = head[: inner.start()], head[inner.end() :]
    if inner.re is _AT_SPLIT:
        title, employer = _clean(first), strip_location(second)
    else:
        # "Example Mutual, Jacksonville, FL - Senior Engineer": the place can sit in
        # either half.
        title, employer = _order(strip_location(first), strip_location(second))
    return title or None, employer or None


@dataclass
class _Draft:
    header: Span
    title: str | None
    employer: str | None
    section: Section
    client: str | None = None
    start: _Date | None = None
    end: _Date | None = None
    is_current: bool = False
    date_text: str = ""  # the line the dates came from, quoted in warnings
    body: list[str] = field(default_factory=list)
    has_bullets: bool = False
    # Read from a single line with the dates, so the line after it may still add a
    # missing employer or title ("Senior Engineer  Jan 2020 - Present", then "ACME Corp").
    single_line: bool = False
    # The employer came from a line above the title ("ACME Corp", then "Senior
    # Engineer | 2020 - Present"), so a later title with only dates is at it too.
    group_employer: bool = False


def _set_dates(draft: _Draft, found: re.Match[str] | None) -> None:
    if found is None:
        return
    draft.start = _parse_date(found.group("start"))
    end = found.group("end")
    if _END_RE.fullmatch(end):
        draft.is_current = True
    else:
        draft.end = _parse_date(end)


def _combine(lines: list[str]) -> tuple[str | None, str | None, str | None]:
    """Title, employer and client from the parts of a header spread over several
    lines ("Example Mutual" then "Senior Data Engineer | Mar 2022 - Present"). A
    "Client:" line gives the client and nothing else."""
    titles: list[str] = []
    employers: list[str] = []
    clients: list[str] = []
    loose: list[str] = []
    for line in lines:
        kind = _label_kind(line)
        if kind == "client":
            client = client_of(line)
            clients += [client] if client else []
            continue
        title, employer = split_title_employer(line)
        if kind == "employer":
            employers += [employer] if employer else []
        elif kind == "title":
            titles += [title] if title else []
        elif title and employer:
            titles.append(title)
            employers.append(employer)
        elif title:
            loose.append(title)
        elif employer:
            employers.append(employer)  # a company name on its own line
    for part in loose:
        if _TITLE_WORDS.search(part) and not titles:
            titles.append(part)
        elif not employers and not (_TITLE_WORDS.search(part) and titles):
            employers.append(part)
        elif not titles:
            titles.append(part)
    if not titles and len(employers) > 1:
        # Neither line names a job-title word: the first one without a company
        # suffix is the title.
        plain = next((i for i, name in enumerate(employers) if not is_company(name)), None)
        if plain is not None:
            titles.append(employers.pop(plain))
    return (
        titles[0] if titles else None,
        employers[0] if employers else None,
        clients[0] if clients else None,
    )


def _rest_of(text: str, found: re.Match[str]) -> str:
    """The header without its date range, a date label or a place."""
    rest = _clean(f"{text[: found.start()]} {text[found.end() :]}")
    labeled = _label(rest) if rest else None
    if labeled is not None and _DATE_LABELS.match(labeled[0]):
        rest = _clean(labeled[1])
    elif rest.endswith(":") and _DATE_LABELS.match(rest.rstrip(":").strip()):
        rest = ""
    if rest and _DATE_LABELS.match(rest.rstrip(":").strip()):
        rest = ""
    return rest


def _read_role_drafts(spans: list[Span], section: Section, inferred: bool = False) -> list[_Draft]:
    """Role drafts from the lines of an experience (or projects) section.

    A role header is a line with a date range, or a line right before a line that
    holds the dates. A header's title and employer may also be spread over the one or
    two short lines before its dates ("Example Mutual", then "Senior Data Engineer",
    then "Mar 2022 - Present"). With `inferred`, the lines come from a resume without
    an experience heading, and a plain line after a role's bullets ends the role.
    """
    drafts: list[_Draft] = []
    current: _Draft | None = None
    # Short lines with no dates since the last bullet or body line. They are part of
    # the next header when the dates come next; otherwise they're body text.
    pending: list[Span] = []

    def attach(span: Span) -> None:
        if current is not None:
            current.body.append(span.id)
            current.has_bullets = current.has_bullets or span.kind is SpanKind.BULLET

    def release() -> None:
        for span in pending:
            attach(span)
        pending.clear()

    def start(header: Span, title: str | None, employer: str | None, date_text: str) -> _Draft:
        nonlocal current
        current = _Draft(
            header=header, title=title, employer=employer, section=section, date_text=date_text
        )
        drafts.append(current)
        return current

    for span in spans:
        if span.kind is SpanKind.HEADING and section_for_heading(span.text) is not None:
            release()
            current = None
            continue
        if span.kind is SpanKind.BULLET:
            release()
            attach(span)
            continue
        text = span.text
        if inferred and looks_like_education(text):
            release()
            current = None
            continue

        # A line, or a styled heading that isn't a section name (Word "Heading 2" roles).
        found = RANGE_RE.search(text)
        if found is not None:
            rest = _rest_of(text, found)
            title, employer = split_title_employer(rest) if rest else (None, None)
            client = client_of(rest) if rest else None
            dates_only = not rest or _is_location(rest)
            if rest and not dates_only and not _header_like(rest):
                release()
                attach(span)  # a sentence that happens to contain dates
                continue
            if pending and (dates_only or title is None or employer is None):
                # The header's parts are on the lines before the dates.
                parts = [p.text for p in pending] + ([rest] if not dates_only else [])
                own_title = title if not dates_only and employer is None else None
                title, employer, client = _combine(parts)
                draft = start(pending[0], title, employer, " ".join([*parts, text]))
                draft.client = client
                draft.body.extend(p.id for p in pending[1:])
                draft.body.append(span.id)
                draft.group_employer = own_title is not None and title == own_title
                pending.clear()
                _set_dates(draft, found)
                continue
            # "Client: Example Bank" just above a full header belongs to that role.
            client_lines = [p for p in pending if _label_kind(p.text) == "client"]
            held = list(pending) if pending and len(client_lines) == len(pending) else []
            if held:
                pending.clear()
            release()
            if dates_only:
                title, employer = None, None
            previous = current
            draft = start(span, title, employer, text)
            draft.client = client or (client_of(held[0].text) if held else None)
            draft.body.extend(p.id for p in held)
            draft.single_line = True
            if (
                title is not None
                and employer is None
                and previous is not None
                and previous.group_employer
                and previous.has_bullets
            ):
                # "ACME Corp", "Senior Engineer | 2022 - Present", bullets, then
                # "Engineer | 2019 - 2021": both titles are at ACME Corp.
                draft.employer = previous.employer
                draft.group_employer = True
            _set_dates(draft, found)
            continue

        kind = _label_kind(text)
        if current is not None and not pending and not current.has_bullets:
            # "Client: Example Bank | 2020 - 2022" then "Role: Guidewire Developer".
            title, employer = split_title_employer(text)
            if kind == "title" and current.title is None:
                current.title = title
                attach(span)
                continue
            if kind == "employer" and current.employer is None:
                current.employer = employer
                attach(span)
                continue
            if kind == "client" and current.client is None:
                # "Guidewire Developer, Demo Infotech | 2019 - 2021", then "Client: ...".
                current.client = client_of(text)
                attach(span)
                continue
            if _fills_header(current, text, kind):
                # "Senior Engineer  Jan 2020 - Present" then "ACME Corp, Dallas, TX".
                if current.employer is None:
                    current.employer = employer or title
                else:
                    current.title = title
                current.single_line = False
                current.group_employer = False
                attach(span)
                continue
        if not _header_like(text) or not (
            _name_like(text) or kind in ("title", "employer", "client")
        ):
            release()
            if inferred and current is not None and current.has_bullets:
                current = None  # a plain line after the bullets ends an inferred role
            else:
                attach(span)
            continue
        if _DATEISH_RE.search(text) and _HEADER_SEPARATOR.search(text):
            # Looks like a header with dates, but they can't be read.
            release()
            title, employer = split_title_employer(_clean(_DATE_TOKEN_RE.sub(" ", text)))
            start(span, title, employer, text)
            continue
        if inferred and current is not None and current.has_bullets:
            current = None
        pending.append(span)
        if len(pending) > 3:
            attach(pending.pop(0))
    release()
    return drafts


def _fills_header(draft: _Draft, text: str, kind: str | None) -> bool:
    """Is this line, right after a one-line header that lacks its employer or title,
    the missing part? It must read like a name and carry no dates or label."""
    missing = draft.employer is None or draft.title is None
    return (
        draft.single_line
        and missing
        and not draft.body
        and kind is None
        and _header_like(text)
        and _name_like(text)
        and not text.rstrip().endswith(":")
        and not _BODY_LABELS.match(text.strip(" :"))
        and not _DATEISH_RE.search(text)
    )


def _resolve(draft: _Draft, today: date, warnings: list[str]) -> Role:
    def role(start: str | None, end: str | None, months: int | None) -> Role:
        return Role(
            title=draft.title,
            employer=draft.employer,
            client=draft.client,
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


def read_roles(
    spans: list[Span], section: Section, today: date, inferred: bool = False
) -> tuple[list[Role], list[str]]:
    warnings: list[str] = []
    roles = [_resolve(d, today, warnings) for d in _read_role_drafts(spans, section, inferred)]
    return roles, warnings


def inferred_experience(spans: list[Span]) -> list[Span]:
    """For a resume without an experience heading: the lines from just before the
    first line with a date range to the end, leaving out the sections that have a
    heading of their own (skills, education, projects, certifications). Contact lines
    and the first line of the resume (the name) never start the block."""
    candidates = [
        span
        for span in spans
        if span.section in _UNHEADED_SECTIONS and span.kind is not SpanKind.HEADING
    ]
    first = next(
        (
            i
            for i, span in enumerate(candidates)
            if RANGE_RE.search(span.text) and not looks_like_education(span.text)
        ),
        None,
    )
    if first is None:
        return []
    begin = first
    while (
        begin > 0
        and first - begin < 3
        and candidates[begin - 1].id != spans[0].id
        and candidates[begin - 1].kind is SpanKind.LINE
        and _header_like(candidates[begin - 1].text)
        and _name_like(candidates[begin - 1].text)
    ):
        begin -= 1
    return candidates[begin:]


_UNHEADED_SECTIONS = {Section.HEADER, Section.SUMMARY, Section.OTHER}


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
# Degree words that can't be a job title ("Associate Developer" is a job).
_STRONG_DEGREE_RE = re.compile(
    r"(?i:\b(?:bachelor(?:'s|s)?|master(?:'s|s)?\s+(?:of|in|degree)|doctor\s+of|doctorate"
    r"|ph\.?\s?d|mba)\b)"
    r"|(?<![\w.])[BM]\.\s?(?:S|A|Sc|E|Eng|Tech|Com|Ed)\.?(?!\w)"
    r"|(?<![\w.])(?:BS|MS|BA|MA)(?=\s+(?:in\s+)?[A-Z])"
    r"|\b(?:BBA|BCA|MCA|BSc|MSc|BTech|MTech|BEng|MEng|LLB|LLM)(?!\w)"
)
_MAX_EDUCATION_WORDS = 20


def looks_like_education(text: str) -> bool:
    """A degree line ("B.S. Computer Science, Example University, 2019"), for resumes
    without an education heading. A sentence that mentions a degree isn't one."""
    if _is_sentence(text) or len(text.split()) > _MAX_EDUCATION_WORDS:
        return False
    if _SCHOOL_RE.search(text) and _DEGREE_RE.search(text):
        return True
    return bool(_STRONG_DEGREE_RE.search(text)) and (
        bool(_SCHOOL_RE.search(text)) or bool(_YEAR_RE.search(text))
    )


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

    experience = in_section(Section.EXPERIENCE)
    inferred = not experience
    if inferred:
        # No experience heading: read roles from the lines that carry date ranges.
        experience = inferred_experience(resume.spans)
    roles, role_warnings = read_roles(experience, Section.EXPERIENCE, today, inferred=inferred)
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
    if inferred and not roles:
        warnings.append("No experience section was found, so no roles or dates were read.")
    elif inferred:
        warnings.append(
            "No experience heading was found, so roles were read from the lines with date "
            "ranges. Check that each role below is right."
        )
    if not (inferred and not roles) and total_years is None:
        warnings.append(
            "No role dates could be read in the experience section, so years of experience "
            "weren't calculated. A line such as \"Data Engineer, Example Corp | Mar 2022 - "
            'Present" works best.'
        )

    role_spans = {role.header_span_id for role in roles} | {
        span_id for role in roles for span_id in role.bullet_span_ids
    }
    has_headings = any(span.kind is SpanKind.HEADING for span in resume.spans)
    metrics: dict[str, list[str]] = {}
    for span in resume.spans:
        if span.kind is not SpanKind.BULLET:
            continue
        in_work = span.section in _RESULT_SECTIONS or span.id in role_spans
        if has_headings and not in_work:
            continue
        found = find_metrics(span.text)
        if found:
            metrics[span.id] = found

    education_spans = in_section(Section.EDUCATION)
    if not education_spans:
        # No education heading: degree lines outside the roles.
        education_spans = [
            span
            for span in resume.spans
            if span.section in _UNHEADED_SECTIONS
            and span.kind is not SpanKind.HEADING
            and span.id not in role_spans
            and looks_like_education(span.text)
        ]

    return Profile(
        roles=roles,
        total_years=total_years,
        education=read_education(education_spans),
        metric_bullets=list(metrics),
        metrics=metrics,
        warnings=warnings,
    )
