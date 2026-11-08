"""Rule-based job-description parser.

Splits a pasted job description into requirements and labels each one required,
preferred or context (responsibilities and background). The Claude-based parser
in claude_jd_parser.py sits behind the same JobParser interface; this one stays as
its fallback and as the baseline it is measured against.

Benefits, pay, legal and logistics lines are dropped, under their own heading or
anywhere else, and so are sentences that only describe the company.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.models import (
    JobDescription,
    JobParserInfo,
    JobParserName,
    MatchMode,
    Priority,
    Requirement,
    Seniority,
)
from app.services.skills import SkillCatalog
from app.services.text import BULLET_ONLY_RE, normalize, strip_bullet

# Heading keywords, checked in this order. Preferred comes first so "Preferred
# Qualifications" isn't read as required, and skip comes before required so
# "Physical requirements" or "Benefits and perks" isn't read as required.
_PREFERRED_HEADING = re.compile(
    r"preferred|nice[\s-]to[\s-]haves?|bonus|desired|desirable|good[\s-]to[\s-]have|pluses"
    r"|\ba plus\b|extra credit|even better|we'?d love|we would love|would be (?:nice|great)"
    r"|\boptional\b|advantageous|\badded advantage\b|stand out|standout"
)
_SKIP_HEADING = re.compile(
    r"who we are|\bbenefits?\b|\bperks?\b|compensation|salary|\bpay\b|pay range|pay transparency"
    r"|total rewards|\brewards\b|what we offer|we offer|our offer|\bin return\b"
    r"|equal (?:employment )?opportunity|\beeo\b|diversity|inclusion|accommodation"
    r"|our values|\bvalues\b|our culture|\bculture\b|why join|why you'll love|why work"
    r"|life at|working at|working here|how to apply|to apply|application process"
    r"|interview process|hiring process|next steps|\blocation\b|work authori[sz]ation"
    r"|authori[sz]ation|\bvisa\b|sponsorship|\blegal\b|disclaimer|privacy|work environment"
    r"|physical (?:demands|requirements)|working conditions|\btravel\b|\bschedule\b"
    r"|working hours|\bhours\b|job type|employment type|\bstart date\b|\bour team\b"
    r"|about the team|meet the team|our story|our mission|background check"
)
_STACK_HEADING = re.compile(
    r"\b(?:our|the|tech|technology|technical)\s+stack\b|tools we use|technologies we use"
    r"|what we use|our tools|our technology"
)
_REQUIRED_HEADING = re.compile(
    r"requirement|qualification|must[\s-]haves?|\bmust\b|you have|you'll need|you will need"
    r"|what you need|we need|\bneeds?\b|looking for|who you are|you are|you're|what you bring"
    r"|you'll bring|you will bring|\bbring\b|required|skills|experience|competenc|background"
    r"|your profile|\bprofile\b|ideal candidate|what it takes|knowledge|abilities|expertise"
)
_CONTEXT_HEADING = re.compile(
    r"responsibilit|what you'll do|what you will do|what you'll be doing|you will be doing"
    r"|the role|your role|role overview|duties|day[\s-]to[\s-]day|day in the life"
    r"|job description|overview|the job|position summary|summary|impact|in this role"
    r"|the opportunity|opportunity|the work|you'll work on|you will work on|accountabilit"
    r"|what you'll own|scope"
)

_LINE_PREFERRED = re.compile(
    r"\b(?:preferred|nice[\s-]to[\s-]have|a plus|is a plus|are a plus|bonus|desirable|desired"
    r"|good[\s-]to[\s-]have|ideally|would be (?:great|nice|a plus)|great to have"
    r"|we'?d love|we would love|extra credit|an advantage|advantageous|is beneficial"
    r"|optional)\b",
    re.IGNORECASE,
)
# "Familiarity with" under a requirements heading is still required; elsewhere it
# reads as preferred.
_FAMILIARITY = re.compile(r"\bfamiliar(?:ity)?\s+with\b", re.IGNORECASE)
_LINE_REQUIRED = re.compile(
    r"\b(?:must|required|requirement|mandatory|minimum|at least|proven|strong"
    r"|you should|should have|should be|we are looking for|we're looking for"
    r"|looking for someone|is essential|are essential|essential|you have|you'll need"
    r"|you will need|you need|need to have|requires|candidates? (?:must|should|will) have)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Lines that aren't requirements
# ---------------------------------------------------------------------------

# Posting details such as "Location: Remote" or "Client: Example Bank".
_META_LINE = re.compile(
    r"^(?:company|client|end client|employer|location|job location|work location|locations"
    r"|employment type|job type|type|contract type|position type|duration|contract length"
    r"|start date|salary|salary range|pay|pay range|base pay|compensation|rate|hourly rate"
    r"|department|team|division|reports to|reporting to|job id|job code|req id|requisition id"
    r"|requisition|posted|date posted|posting date|travel|schedule|shift|hours|work model"
    r"|work arrangement|work mode|workplace type|visa|visa status|work authori[sz]ation"
    r"|openings|positions|number of openings|interview|interview mode|benefits)\s*:",
    re.IGNORECASE,
)
# Benefit, pay, legal and how-to-apply wording that is never a requirement.
_ALWAYS_BOILERPLATE = re.compile(
    r"[$\u00a3\u20ac]\s?\d[\d,.]*\s?[kK]?\s*(?:-|\u2013|\u2014|to)\s*[$\u00a3\u20ac]?\s?\d"
    r"|[$\u00a3\u20ac]\s?\d[\d,.]*\s?[kK]?\s*(?:/|per|an|a)\s*(?:hr|hour|year|yr|annum|month)\b"
    r"|\bsalary\b|\bpay (?:range|rate|band|scale|transparency)\b|\bbase pay\b"
    r"|\b(?:total|competitive|base) compensation\b|\bcompensation (?:package|range)\b"
    r"|\b(?:annual|performance|signing|sign-on|target) bonus\b"
    r"|\b401\s?\(?k\)?|\bretirement (?:plan|savings)\b|\bstock options\b"
    r"|\b(?:equity|stock) (?:grant|package|awards?)\b|\bplus equity\b|\bESPP\b"
    r"|\bpaid time off\b|\bPTO\b|\bpaid (?:vacation|holidays|leave)\b"
    r"|\bunlimited (?:pto|vacation)\b"
    r"|\b(?:parental|maternity|paternity|sick) leave\b"
    r"|\bequal (?:employment )?opportunit|\baffirmative action\b|\bwithout regard to\b"
    r"|\bregardless of (?:race|age|gender|sex|religion)|\bprotected veteran"
    r"|\breasonable accommodations?\b|\bE-Verify\b|\bbackground (?:check|screening)s?\b"
    r"|\bdrug (?:test|screen)|\bsponsorship\b|\bH-?1B\b"
    r"|\b(?:unable to|not able to|cannot|can't|will not|won't|do not|does not|not) sponsor\b"
    r"|\bsponsor (?:a |an )?(?:visa|visas|work|employment|H-?1B)"
    r"|\bauthori[sz]ed to work\b|\bwork authori[sz]ation\b|\bwork permit\b"
    r"|\bhow to apply\b|^to apply\b|\bto apply,? (?:please|send|email|submit|visit|click)"
    r"|\bapply (?:now|today|online|here)\b|\bapply (?:via|through) (?:our|the|this)\b"
    r"|\b(?:send|submit|share|email|forward) (?:us )?(?:your|a)\s+(?:updated\s+)?"
    r"(?:resume|cv|application)\b"
    r"|[\w.+-]+@[\w-]+\.[\w.]+",
    re.IGNORECASE,
)
# Benefit wording that a requirement can also use ("experience with health
# insurance claims"): dropped only when the line asks for nothing.
_BENEFIT_WORDING = re.compile(
    r"\b(?:medical|health|dental|vision|life|disability)(?:\s*(?:,|and|&)\s*"
    r"(?:medical|health|dental|vision|life|disability))*\s+(?:insurance|coverage|benefits"
    r"|plans?)\b"
    r"|\bvacation\b|\bholidays\b|\btuition\b|\blearning budget\b|\b(?:education|learning"
    r"|wellness|home office|remote work|commuter|phone|internet) (?:stipend|allowance|budget)\b"
    r"|\bwellness\b|\bgym\b|\bfree (?:lunch|meals|snacks)\b|\brelocation\b|\bbenefits\b"
    r"|\bperks\b|\bcompetitive (?:pay|salary|package)\b|\bhybrid schedule\b|\bremote days?\b"
    r"|\bdays (?:a|per) week in (?:the )?office\b|\bflexible (?:hours|schedule|working)\b"
    r"|\bdiversity\b|\binclusive\b|\bcompensation\b|\bpension\b"
    r"|\b(?:role|position|job|team) is (?:fully |100% )?(?:remote|hybrid|on-?site|in[- ]office)\b"
    r"|\bremote within\b|\bdays? (?:a|per) week (?:in|on)[- ](?:the )?(?:office|site)\b",
    re.IGNORECASE,
)
_ASKS_FOR_SOMETHING = re.compile(
    r"\b(?:experience|experienced|knowledge|familiar|familiarity|understanding|proficien\w*"
    r"|expertise|ability|able to|skills?|background in|degree|certif\w*|years?|hands-on"
    r"|track record|must|required|requires?|should|working knowledge|exposure)\b",
    re.IGNORECASE,
)
# A sentence about the candidate or the job, as opposed to the company.
_ABOUT_THE_JOB = re.compile(
    r"\b(?:you|your|you'll|you're|yourself|candidates?|will|need|needs|responsib\w*|duties)\b",
    re.IGNORECASE,
)


def _boilerplate(sentence: str) -> bool:
    if _ALWAYS_BOILERPLATE.search(sentence):
        return True
    return bool(_BENEFIT_WORDING.search(sentence)) and not _ASKS_FOR_SOMETHING.search(sentence)


# Verbs that start a duty written as an instruction ("Work with analysts to ...").
_DUTY_VERB_LIST = (
    "act advise analyze architect assess assist automate build champion coach "
    "collaborate communicate conduct contribute coordinate create debug define deliver "
    "deploy design develop document drive educate engage enhance ensure establish "
    "evaluate execute facilitate gather guide help identify implement improve influence "
    "integrate investigate lead maintain manage mentor migrate model monitor operate "
    "optimize own participate partner perform plan prepare present prioritize produce "
    "propose prototype provide research resolve review run scale serve ship shape solve "
    "support test track train translate troubleshoot tune update use validate work write"
)
_DUTY_VERBS = frozenset(_DUTY_VERB_LIST.split())
# First words of a sentence about the job rather than the company ("The engineer ...").
_NOT_A_NAME_LIST = "the this these that in as at it a an on for with each every all your you"
_NOT_A_NAME = frozenset(_NOT_A_NAME_LIST.split())


def _about_the_company(sentence: str, catalog: SkillCatalog) -> bool:
    """A prose sentence that only describes the company ("Demo Freight Systems is
    growing the team that runs our order platform."): it starts with a name or "We"
    rather than a duty verb, doesn't address the candidate or the role, asks for
    nothing, and names no skill other than a domain (which a company name such as
    "Example Insurance" can supply)."""
    first = re.match(r"[A-Za-z']+", sentence)
    if first is None or not first.group()[0].isupper():
        return False
    if first.group().lower() in _DUTY_VERBS | _NOT_A_NAME:
        return False
    if any(
        pattern.search(sentence)
        for pattern in (_ABOUT_THE_JOB, _ASKS_FOR_SOMETHING, _LINE_REQUIRED, _LINE_PREFERRED)
    ):
        return False
    return all(catalog.categories.get(skill) == "domain" for skill in catalog.skills_in(sentence))


def _clean_items(item: str, is_bullet: bool, section: Priority, catalog: SkillCatalog) -> list[str]:
    """The item without its boilerplate sentences. A line whose every sentence is kept
    stays whole; otherwise the kept sentences become items of their own."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(item) if s.strip()]
    kept = [
        s
        for s in sentences
        if not _boilerplate(s)
        and not (not is_bullet and section is Priority.CONTEXT and _about_the_company(s, catalog))
    ]
    if len(kept) == len(sentences):
        return [item]
    return kept


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
_ABOUT_HEADING = re.compile(r"^about\b[\w\s&.,'-]*$", re.IGNORECASE)


def _shouted(text: str) -> bool:
    """An all-caps line such as "WHAT WE OFFER"."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def _heading_priority(
    line: str, catalog: SkillCatalog, allow_unknown: bool = True
) -> Priority | str | None:
    """Return a Priority for a section heading, "skip" for sections to ignore, or
    None if the line isn't a heading.

    A short line is a heading when it holds a known heading word, ends with a colon
    or is written in capitals. A heading with no known word ("Our Story:") starts a
    context section, so it ends the section above it.
    """
    text = line.strip()
    if not text or text.endswith((".", ",", ";")):
        return None
    # Bullets are items, never headings ("- Excellent communication skills").
    if strip_bullet(text)[1]:
        return None
    if len(text.rstrip(":").split()) > _MAX_HEADING_WORDS or _YEARS.search(text):
        return None
    key = text.rstrip(":").strip().lower()
    if _ABOUT_HEADING.match(key) and not text.endswith("?"):
        # "About the role" describes the job, "About you" lists requirements,
        # anything else ("About Acme", "About Example Insurance") is company
        # background, even when the company's name holds a skill word.
        if re.search(r"\b(role|job|position|opportunity)\b", key):
            return Priority.CONTEXT
        if re.search(r"\byou\b", key):
            return Priority.REQUIRED
        return "skip"
    # A line naming a real skill is a requirement, not a heading ("Python experience").
    if catalog.skills_in(text):
        return None
    if _PREFERRED_HEADING.search(key):
        return Priority.PREFERRED
    if _SKIP_HEADING.search(key):
        return "skip"
    if _STACK_HEADING.search(key):
        return Priority.CONTEXT
    if _REQUIRED_HEADING.search(key):
        return Priority.REQUIRED
    if _CONTEXT_HEADING.search(key):
        return Priority.CONTEXT
    if allow_unknown and (text.endswith(":") or _shouted(text)):
        return Priority.CONTEXT
    return None


def _line_priority(text: str, section: Priority) -> Priority:
    if _LINE_PREFERRED.search(text):
        return Priority.PREFERRED
    if _FAMILIARITY.search(text) and section is not Priority.REQUIRED:
        return Priority.PREFERRED
    if section is Priority.CONTEXT and _LINE_REQUIRED.search(text):
        return Priority.REQUIRED
    return section


def min_years_in(text: str) -> int | None:
    """The years a line asks for: 5 for "5+ years", 3 for "3-5 years"."""
    match = _YEARS.search(text)
    return int(match.group(1)) if match else None


def seniority_for(title: str | None, min_years: int | None) -> Seniority:
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
    """Bullets stay whole; prose lines are split into sentences, so "Build models in
    Python. Work with stakeholders." is two items."""
    items: list[str] = []
    for line in lines:
        text, is_bullet = strip_bullet(line)
        if not text:
            continue
        if is_bullet:
            items.append(text)
        else:
            items.extend(s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip())
    return items


def job_min_years(requirements: list[Requirement]) -> int | None:
    """The job's years: the first required line that states years, else the first
    line of any priority that does."""
    required_years = [
        r.min_years for r in requirements if r.priority is Priority.REQUIRED and r.min_years
    ]
    any_years = [r.min_years for r in requirements if r.min_years]
    return required_years[0] if required_years else (any_years[0] if any_years else None)


def match_mode_for(text: str) -> MatchMode:
    return MatchMode.ANY if _ANY_OF.search(text) else MatchMode.ALL


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

        # An all-caps first line is the job's title, not a heading.
        top = section == "preamble" and title is None
        heading = _heading_priority(line, catalog, allow_unknown=not top)
        if heading is not None:
            section = heading
            continue

        if section == "skip":
            continue
        text, is_bullet = strip_bullet(line)
        if _META_LINE.match(text):
            continue  # "Location: Remote", "Client: Example Bank"
        if section == "preamble":
            if title is None and not is_bullet and len(text.split()) <= 12 and "." not in text:
                title = text
                continue
            # Company intros are skipped unless they name a skill or a years requirement.
            # A domain alone ("software for insurers") must come with requirement wording.
            skills = catalog.skills_in(text)
            tools = [s for s in skills if catalog.categories.get(s) != "domain"]
            asks = _LINE_REQUIRED.search(text) or _LINE_PREFERRED.search(text)
            if not (tools or min_years_in(text) or (skills and asks)):
                continue
            base = Priority.CONTEXT
        else:
            assert isinstance(section, Priority)
            base = section

        for item in _items([line]):
            for kept in _clean_items(item, is_bullet, base, catalog):
                grouped.append((_line_priority(kept, base), kept))

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
                skills=catalog.requirement_skills(text),
                match_mode=match_mode_for(text),
                min_years=min_years_in(text),
            )
        )

    job_years = job_min_years(requirements)

    return JobDescription(
        title=title,
        seniority=seniority_for(title, job_years),
        min_years=job_years,
        requirements=requirements,
    )


# ---------------------------------------------------------------------------
# The parser interface
# ---------------------------------------------------------------------------


@dataclass
class ParsedJob:
    job: JobDescription
    parser: JobParserInfo
    warnings: list[str] = field(default_factory=list)


class JobParser(Protocol):
    def parse(self, raw: str, catalog: SkillCatalog) -> ParsedJob: ...


class RuleJobParser:
    """The rule-based parser above, behind the JobParser interface."""

    def parse(self, raw: str, catalog: SkillCatalog) -> ParsedJob:
        return ParsedJob(
            job=parse_job_description(raw, catalog),
            parser=JobParserInfo(name=JobParserName.RULES),
        )
