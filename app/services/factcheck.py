"""Deterministic fact checker for rewrite suggestions.

Given a source bullet and a candidate rewrite, it lists every fact the rewrite
states that the source doesn't. A rewrite passes only when that list is empty.
It is the safety gate for suggestions, so when a rule is unsure it rejects: a
good rewrite thrown away costs less than an invented fact shown to a recruiter.

What counts as an added fact:

- A number that isn't in the source, after normalizing how it is written. "40+",
  "40 or more" and "over 40" are the same; "five hours" is "5 hours" and "90
  minutes" is "1.5 hours"; "$310K" is "$310,000"; "35 percent" is "35%"; "p95" is
  the "95th percentile". A unit or a bound ("under", "+") that the source doesn't
  give the number also counts. Multiplier words ("doubled", "twice", "half") are
  numbers, so "improved" becoming "doubled" fails.
- A year, month, quarter or other date that isn't in the source.
- A catalog skill the source doesn't name. An acronym and its spelled-out form
  ("CI/CD" and "continuous integration and delivery") count as the same skill.
- A capitalized name (an employer, client, product or tool) whose words aren't in
  the source, wherever it stands ("at Amazon", "for Acme Corp"). An acronym of
  words in the source ("AKS" for "Azure Kubernetes Service") is allowed, and so is a
  vendor name directly before a product the source names ("Amazon EKS" for "EKS").
  Spelling an acronym out in capitalized words is not.
- A certification ("certified", "licensed", "PMP") the source doesn't mention.
- Scope the source doesn't claim: leadership or ownership words ("led", "owned",
  "designed"), absolutes ("all", "company-wide", "eliminated"), a new kind of
  result ("reducing" when the source states no reduction), a dropped hedge
  ("helped"), and a frequency ("daily") the source doesn't give.
- A rewrite more than twice as long as the source.

Reordering words, a stronger verb for the same action and trimming all pass.
"""

import itertools
import re
from dataclasses import dataclass
from enum import StrEnum

from app.services.skills import SkillCatalog, get_catalog
from app.services.text import normalize, strip_bullet


class FactKind(StrEnum):
    NUMBER = "number"
    DATE = "date"
    SKILL = "skill"
    NAME = "name"
    CERTIFICATION = "certification"
    SCOPE = "scope"
    LENGTH = "length"


@dataclass(frozen=True)
class AddedFact:
    kind: FactKind
    text: str  # the words in the rewrite (or, for a dropped hedge, in the source)
    reason: str  # one sentence a person can read


@dataclass(frozen=True)
class FactCheckResult:
    passed: bool
    added: tuple[AddedFact, ...]


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def _word_list(text: str) -> list[str]:
    return text.split()


_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_UNITS_WORDS = _word_list(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
)
_TENS_WORDS = _word_list("twenty thirty forty fifty sixty seventy eighty ninety")
_WORD_VALUES = {word: i for i, word in enumerate(_UNITS_WORDS)} | {
    word: 20 + 10 * i for i, word in enumerate(_TENS_WORDS)
}
_WORD_NUMBER = (
    rf"(?:(?:{'|'.join(_TENS_WORDS)})(?:[\s-](?:{'|'.join(_UNITS_WORDS[1:10])}))?"
    rf"|{'|'.join(_UNITS_WORDS)})"
)
_MULTIPLIERS = {
    "double": 2.0,
    "doubled": 2.0,
    "doubles": 2.0,
    "doubling": 2.0,
    "twice": 2.0,
    "twofold": 2.0,
    "triple": 3.0,
    "tripled": 3.0,
    "triples": 3.0,
    "tripling": 3.0,
    "threefold": 3.0,
    "thrice": 3.0,
    "quadruple": 4.0,
    "quadrupled": 4.0,
    "quadrupling": 4.0,
    "fourfold": 4.0,
    "tenfold": 10.0,
    "half": 0.5,
    "halve": 0.5,
    "halved": 0.5,
    "halving": 0.5,
}
# "second" is left out: it is far more often a unit of time than an ordinal.
_ORDINALS = {
    "first": 1,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_MAGNITUDES = {
    "dozens": 12.0,
    "hundreds": 100.0,
    "thousands": 1e3,
    "millions": 1e6,
    "billions": 1e9,
}
_SCALES = {
    "hundred": 100.0,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
    "k": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "b": 1e9,
    "bn": 1e9,
}
_CURRENCY_SYMBOLS = {"$": "USD", "\u20ac": "EUR", "\u00a3": "GBP", "\u20b9": "INR"}
_CURRENCY_WORDS = {
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "pounds": "GBP",
    "gbp": "GBP",
    "rupees": "INR",
    "inr": "INR",
}
_SECONDS = {
    "ms": 0.001,
    "msec": 0.001,
    "millisecond": 0.001,
    "sec": 1.0,
    "second": 1.0,
    "min": 60.0,
    "minute": 60.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "day": 86_400.0,
    "wk": 604_800.0,
    "week": 604_800.0,
    "mo": 2_592_000.0,
    "month": 2_592_000.0,
    "quarter": 7_776_000.0,
    "yr": 31_536_000.0,
    "year": 31_536_000.0,
}
_BYTES = {"kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15}

_CORE_RE = re.compile(
    r"(?P<pctl>(?<![A-Za-z0-9])[pP](?P<pval>\d{2,3}(?:\.\d+)?)(?![A-Za-z0-9]))"
    rf"|(?P<cur>[$\u20ac\u00a3\u20b9])\s?(?P<cnum>{_DIGITS})"
    rf"|(?<![A-Za-z0-9_.])(?P<num>{_DIGITS})"
    r"|(?i:\b(?P<ascale>an?\s+(?:hundred|thousand|million|billion))\b)"
    r"|(?i:\b(?P<dozen>(?:an?\s+)?dozen)\b)"
    rf"|(?i:\b(?P<word>{_WORD_NUMBER})\b)"
    rf"|(?i:\b(?P<mult>{'|'.join(_MULTIPLIERS)})\b)"
    rf"|(?i:\b(?P<ord>{'|'.join(_ORDINALS)})\b)"
    rf"|(?i:\b(?P<mag>{'|'.join(_MAGNITUDES)})\b)"
)
_SCALE_AFTER_DIGITS = re.compile(
    r"(?i:\s?(?P<word>hundred|thousand|million|billion|trillion)\b)"
    r"|(?P<letter>MM|bn|BN|[kKMB])(?![A-Za-z])"
)
_SCALE_AFTER_WORD = re.compile(r"(?i:\s+(?P<word>hundred|thousand|million|billion)\b)")
_ORDINAL_SUFFIX = re.compile(r"(?:st|nd|rd|th)\b")
_PERCENTILE_AFTER = re.compile(r"(?i:\s+percentile\b)")
_AT_LEAST_AFTER = re.compile(r"\+|(?i:\s?(?:or\s+more|or\s+greater|plus)\b)")
_AT_MOST_AFTER = re.compile(r"(?i:\s?or\s+(?:fewer|less)\b)")
_UNIT_AFTER = re.compile(
    r"(?i:\s?-?(?:"
    r"(?P<pct>%|percent\b|per\s?cent\b)"
    r"|(?P<x>[x\u00d7](?![A-Za-z0-9])|times\b|-?fold\b)"
    r"|(?P<time>milliseconds?|msecs?|ms|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?"
    r"|weeks?|wks?|months?|mos?|quarters?|years?|yrs?)\b"
    r"|(?P<data>[kmgtp]b)\b"
    r"|(?P<money>dollars?|usd|euros?|eur|pounds|gbp|rupees|inr)\b"
    r"))"
)
_AT_MOST_BEFORE = re.compile(
    r"(?:(?i:\b(?:no\s+more\s+than|under|below|less\s+than|fewer\s+than|at\s+most|up\s+to"
    r"|within))|<=?|\u2264)\s*$"
)
_AT_LEAST_BEFORE = re.compile(
    r"(?:(?i:\b(?:more\s+than|over|above|at\s+least|upwards\s+of|exceeding|greater\s+than"
    r"|in\s+excess\s+of))|>=?|\u2265)\s*$"
)
_MONEY_BEFORE = re.compile(r"\b(?P<code>USD|EUR|GBP|INR)\s?$")
_RANGE_JOIN = re.compile(r"(?i:\s*(?:-|\u2013|\u2014|to|and|or|through)\s*)")


@dataclass
class _Quantity:
    start: int
    end: int
    value: float  # with any scale applied: "2M" is 2,000,000
    unit: str | None = None  # %, x, time, bytes, USD..., percentile, ordinal, magnitude
    base: float = 0.0  # value in the unit's base (seconds for time, bytes for data)
    bound: str | None = None  # at_least or at_most
    is_year: bool = False

    def set_unit(self, unit: str | None, factor: float = 1.0) -> None:
        self.unit = unit
        self.base = self.value * factor


def _unit_of(found: re.Match[str]) -> tuple[str, float]:
    if found.group("pct"):
        return "%", 1.0
    if found.group("x"):
        return "x", 1.0
    if time := found.group("time"):
        key = time.lower()
        for name, seconds in sorted(_SECONDS.items(), key=lambda item: -len(item[0])):
            if key.startswith(name):
                return "time", seconds
    if data := found.group("data"):
        return "bytes", _BYTES[data.lower()]
    return _CURRENCY_WORDS[found.group("money").lower()], 1.0


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _word_value(text: str) -> float:
    parts = re.split(r"[\s-]+", text.lower())
    return float(sum(_WORD_VALUES[p] for p in parts))


_ONE_BEFORE = re.compile(r"(?i:\b(?:each|every|no|any|some|which|this|that)\s+)$")
_ONE_AFTER = re.compile(r"(?i:\s+(?:of|another)\b|-(?:time|off|on-one|way|stop|click)\b)")


def _pronoun_one(text: str, core: re.Match[str]) -> bool:
    """ "each one", "no one", "one of", "one-time": "one" that isn't a count."""
    if core.group("word").lower() != "one":
        return False
    return bool(_ONE_BEFORE.search(text, 0, core.start()) or _ONE_AFTER.match(text, core.end()))


def _quantities(text: str) -> list[_Quantity]:
    found_all: list[_Quantity] = []
    for core in _CORE_RE.finditer(text):
        start, end = core.span()
        quantity: _Quantity
        if core.group("pctl"):
            quantity = _Quantity(start, end, _number(core.group("pval")))
            quantity.set_unit("percentile")
        elif core.group("mult"):
            quantity = _Quantity(start, end, _MULTIPLIERS[core.group("mult").lower()])
            quantity.set_unit("x")
        elif core.group("mag"):
            quantity = _Quantity(start, end, _MAGNITUDES[core.group("mag").lower()])
            quantity.set_unit("magnitude")
        elif core.group("ord"):
            quantity = _Quantity(start, end, float(_ORDINALS[core.group("ord").lower()]))
            if percentile := _PERCENTILE_AFTER.match(text, end):
                quantity.end = percentile.end()
                quantity.set_unit("percentile")
            else:
                quantity.set_unit("ordinal")
        else:
            if core.group("ascale"):
                value = _SCALES[core.group("ascale").split()[-1].lower()]
            elif core.group("dozen"):
                value = 12.0
            elif core.group("word"):
                if _pronoun_one(text, core):
                    continue
                value = _word_value(core.group("word"))
            else:
                value = _number(core.group("cnum") or core.group("num"))
            quantity = _Quantity(start, end, value)
            quantity.base = value
            is_digits = bool(core.group("num") or core.group("cnum"))
            scale = (
                _SCALE_AFTER_DIGITS.match(text, end)
                if is_digits
                else _SCALE_AFTER_WORD.match(text, end)
                if core.group("word")
                else None
            )
            if scale is not None:
                quantity.value *= _SCALES[(scale.group("word") or scale.group("letter")).lower()]
                quantity.end = scale.end()
            if core.group("cur"):
                quantity.set_unit(_CURRENCY_SYMBOLS[core.group("cur")])
            elif money := _MONEY_BEFORE.search(text, 0, start):
                quantity.start = money.start()
                quantity.set_unit(money.group("code"))
            if is_digits and scale is None and (suffix := _ORDINAL_SUFFIX.match(text, end)):
                quantity.end = suffix.end()
                if percentile := _PERCENTILE_AFTER.match(text, quantity.end):
                    quantity.end = percentile.end()
                    quantity.set_unit("percentile")
                else:
                    quantity.set_unit("ordinal")
            if quantity.unit is None or quantity.unit in _CURRENCY_SYMBOLS.values():
                if at_least := _AT_LEAST_AFTER.match(text, quantity.end):
                    quantity.bound = "at_least"
                    quantity.end = at_least.end()
                elif at_most := _AT_MOST_AFTER.match(text, quantity.end):
                    quantity.bound = "at_most"
                    quantity.end = at_most.end()
            if quantity.unit is None and (unit := _UNIT_AFTER.match(text, quantity.end)):
                name, factor = _unit_of(unit)
                quantity.set_unit(name, factor)
                quantity.end = unit.end()
            raw = core.group("num") or ""
            quantity.is_year = (
                bool(re.fullmatch(r"(?:19[5-9]|20[0-4])\d", raw))
                and quantity.unit is None
                and quantity.value == float(raw)
            )
            # "5G" or "3D": digits glued to letters are a name, not a quantity.
            if is_digits and quantity.end == end and re.match(r"[A-Za-z]", text[end : end + 1]):
                continue
        if quantity.bound is None:
            if _AT_MOST_BEFORE.search(text, 0, quantity.start):
                quantity.bound = "at_most"
            elif _AT_LEAST_BEFORE.search(text, 0, quantity.start):
                quantity.bound = "at_least"
            if quantity.bound is not None:
                qualifier = _AT_MOST_BEFORE.search(text, 0, quantity.start) or (
                    _AT_LEAST_BEFORE.search(text, 0, quantity.start)
                )
                assert qualifier is not None
                quantity.start = qualifier.start()
        found_all.append(quantity)

    # "from 5 to 90 minutes": the first number of a range takes the second's unit.
    for left, right in itertools.pairwise(found_all):
        if (
            left.unit is None
            and right.unit is not None
            and not left.is_year
            and _RANGE_JOIN.fullmatch(text, left.end, right.start)
        ):
            factor = right.base / right.value if right.value else 1.0
            left.set_unit(right.unit, factor)
    return found_all


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _supported(quantity: _Quantity, source: list[_Quantity]) -> bool:
    for candidate in source:
        if quantity.bound is not None and candidate.bound != quantity.bound:
            continue
        if quantity.unit is None:
            if _close(candidate.value, quantity.value):
                return True
        elif candidate.unit == quantity.unit and _close(candidate.base, quantity.base):
            return True
    return False


# ---------------------------------------------------------------------------
# Dates other than years
# ---------------------------------------------------------------------------

_MONTH_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November"
    r"|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b"
)
_PERIOD_RE = re.compile(r"\b(?:Q[1-4]|H[12]|FY\s?\d{2,4})\b")


# ---------------------------------------------------------------------------
# Names and acronyms
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.#+&'\u2019]*")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_ACRONYM_STOPWORDS = {"of", "and", "the", "for", "to", "in", "on", "a", "an", "&"}
_SENTENCE_END = re.compile(r"[.!?:;]\s*$")
# Words that often start a bullet or a clause and are never names on their own.
_COMMON_STARTS = set(
    _word_list(
        """
    a an the as at by for from in into on onto of over to under with within without using
    across after before during through throughout via per and or but so then also each both
    this that these those our my their its his her we they it i while when where which who
    built cut set ran led wrote made drove grew took gave held kept met won sold began
    brought bought taught found put spent sent went became chose rebuilt rewrote shot split
    spun struck swept threw told understood upheld oversaw undertook
    build run operate own lead write manage maintain design develop deliver create drive
    support partner work help serve use reduce improve automate migrate deploy configure
    implement mentor review analyze analyse define document monitor schedule test train
    tune optimize optimise launch ship plan coordinate collaborate integrate refactor model
    architect engineer establish introduce standardize standardise streamline modernize
    modernise consolidate containerize containerise fine tuned scale secure translate
    prepare present publish raise rewrite debug fix handle process query report research
    resolve respond troubleshoot upgrade validate verify
    """
    )
)
_VENDOR_PRODUCTS: dict[str, set[str]] = {
    "amazon": {
        "aws",
        "eks",
        "ecs",
        "ec2",
        "s3",
        "rds",
        "redshift",
        "kinesis",
        "dynamodb",
        "lambda",
        "glue",
        "sagemaker",
        "aurora",
        "emr",
        "athena",
        "sqs",
        "sns",
        "cloudwatch",
        "bedrock",
        "quicksight",
    },
    "microsoft": {"azure", "aks", "excel", "dynamics", "sharepoint", "powershell", "synapse"},
    "azure": {"aks", "synapse", "cosmos"},
    "google": {"gcp", "bigquery", "gke", "vertex", "firebase", "looker", "dataflow", "dataproc"},
    "apache": {
        "kafka",
        "spark",
        "pyspark",
        "airflow",
        "hadoop",
        "hive",
        "beam",
        "flink",
        "cassandra",
        "nifi",
        "superset",
        "iceberg",
        "tomcat",
        "maven",
        "solr",
        "zookeeper",
    },
}
_VENDOR_PRODUCTS["aws"] = _VENDOR_PRODUCTS["amazon"] - {"aws"}
_VENDOR_PRODUCTS["gcp"] = _VENDOR_PRODUCTS["google"] - {"gcp"}


def _norm(token: str) -> str:
    token = re.sub(r"['\u2019]s?$", "", token.rstrip("."))
    return token.lower()


def _forms(token: str) -> set[str]:
    base = _norm(token)
    forms = {base}
    if base.endswith("es") and len(base) > 4:
        forms.add(base[:-2])
    if base.endswith("s") and len(base) > 3:
        forms.add(base[:-1])
    return forms


def _source_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for found in _TOKEN_RE.finditer(text):
        tokens |= _forms(found.group())
        tokens |= {part.lower() for part in found.group().split(".") if part}
    return tokens


def _name_like(token: str) -> bool:
    has_upper = any(c.isupper() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    return has_alpha and (has_upper or has_digit)


def _is_acronym(token: str) -> bool:
    core = token[:-1] if token.endswith("s") and token[:-1].isupper() else token
    return 2 <= len(core) <= 6 and core.isalpha() and core.isupper()


def _acronym_letters(token: str) -> str:
    return (token[:-1] if token.endswith("s") and token[:-1].isupper() else token).lower()


def _content_words(text: str) -> list[re.Match[str]]:
    return [w for w in _WORD_RE.finditer(text) if w.group().lower() not in _ACRONYM_STOPWORDS]


def _initials_match(words: list[re.Match[str]], letters: str) -> list[tuple[int, int]]:
    """Character spans of word runs whose initials spell `letters`."""
    spans: list[tuple[int, int]] = []
    size = len(letters)
    for i in range(len(words) - size + 1):
        window = words[i : i + size]
        if "".join(w.group()[0].lower() for w in window) == letters:
            spans.append((window[0].start(), window[-1].end()))
    return spans


def _descriptive(term: str) -> bool:
    """A plain-words catalog term ("continuous integration", "Machine learning") as
    opposed to a product name ("GitHub", "Ubuntu")."""
    words = term.split()
    if term == term.lower():
        return True
    return len(words) > 1 and all(w == w.lower() for w in words[1:]) and words[0][1:].islower()


def _variant(a: str, b: str) -> bool:
    """Two spellings of one name: word by word equal, or one word is the other plus a
    lowercase ending ("REST" and "RESTful", "React" and "React.js"). "Git" and
    "GitHub" are not variants: the ending is a new capitalized word."""
    words_a, words_b = a.split(), b.split()
    if len(words_a) != len(words_b):
        return False
    for x, y in zip(words_a, words_b, strict=True):
        short, long = sorted((x, y), key=len)
        if not long.lower().startswith(short.lower()):
            return False
        ending = long[len(short) :]
        if ending and not (ending == ending.lower() or ending.lower() == ".js"):
            return False
    return True


def _acronym_of(short: str, long: str) -> bool:
    if not _is_acronym(short):
        return False
    return bool(_initials_match(_content_words(long), _acronym_letters(short)))


# ---------------------------------------------------------------------------
# Certifications, scope, results, hedges and frequencies
# ---------------------------------------------------------------------------

_CERT_RE = re.compile(
    r"(?i:\b(?:certified|certification|certifications|certificate|certificates|accredited"
    r"|accreditation|licensed|chartered)\b)"
    r"|\b(?:PMP|CAPM|CKA|CKAD|CKS|CISSP|CISM|CISA|CEH|OSCP|CCNA|CCNP|CCIE|CSM|CSPO|PSM|SAFe"
    r"|CPA|CFA|FRM|ITIL|RHCE|RHCSA|MCSE|MCSA|TOGAF)\b"
)

_LEADERSHIP: dict[str, str] = {
    "lead": r"\b(?:led|lead|leads|leading)\b",
    "own": r"\b(?:own|owns|owned|owning|owner|owners|ownership)\b",
    "manage": r"\b(?:manage|manages|managed|managing|manager|managers|management)\b",
    "head": r"\b(?:headed|heading\s+up)\b",
    "spearhead": r"\bspearhead\w*",
    "direct": r"\b(?:directed|directing|director)\b",
    "supervise": r"\bsupervis\w*",
    "oversee": r"\b(?:oversaw|oversee|oversees|overseeing|overseen|oversight)\b",
    "architect": r"\b(?:architect|architects|architected|architecting)\b",
    "design": r"\b(?:design|designs|designed|designing)\b",
    "found": r"\b(?:founded|co-founded|cofounded|founder|co-founder|founding)\b",
    "initiate": r"\binitiat\w*",
    "pioneer": r"\bpioneer\w*",
    "champion": r"\bchampion\w*",
    "mentor": r"\bmentor\w*",
    "coach": r"\bcoach\w*",
    "charge": r"\bin\s+charge\b",
    "strategy": r"\bstrateg\w*",
    "sole": r"\b(?:sole|solely|single-handedly|singlehandedly|independently)\b",
    "senior": r"\b(?:senior|principal|chief)\b",
}
_ABSOLUTES: dict[str, str] = {
    "all": r"\ball\b",
    "every": r"\bevery\b",
    "entire": r"\b(?:entire|entirely|whole)\b",
    "always": r"\balways\b",
    "never": r"\bnever\b",
    "fully": r"\b(?:fully|completely)\b",
    "org-wide": (
        r"\b(?:company|organi[sz]ation|org|enterprise|firm|department|business)[\s-]?wide\b"
        r"|\bacross\s+the\s+(?:company|organi[sz]ation|org|enterprise|firm|business"
        r"|department)\b"
    ),
    "end-to-end": r"\bend[\s-]to[\s-]end\b",
    "eliminate": r"\b(?:eliminat\w*|eradicat\w*|prevent\w*)",
    "global": r"\b(?:global|globally|worldwide|nationwide|international\w*)\b",
    "executive": r"\b(?:executives?|c-suite|c-level|board\s+of\s+directors)\b",
}
# Claims about the work itself that models like to add.
_QUALIFIERS: dict[str, str] = {
    "real-time": r"\breal[\s-]?time\b",
    "large-scale": r"\blarge[\s-]scale\b",
    "high-load": r"\bhigh[\s-](?:volume|traffic|availability|throughput|performance)\b",
    "mission-critical": r"\bmission[\s-]critical\b",
    "grade": r"\b(?:enterprise|production)[\s-]grade\b",
    "cloud-native": r"\bcloud[\s-]native\b",
    "scalable": r"\bscal(?:able|ability)\b",
    "distributed": r"\bdistributed\b",
    "low-latency": r"\blow[\s-]latency\b",
    "fault-tolerant": r"\bfault[\s-]toleran\w*",
    "recognition": r"\b(?:award\w*|recogni[sz]ed|promoted|patent\w*)\b",
}
_RESULTS: dict[str, str] = {
    "decrease": (
        r"\b(?:cut|cuts|cutting|reduc\w*|lower(?:ed|ing|s)?|decreas\w*|shorten\w*|shrank"
        r"|shrink\w*|shrunk|slash\w*|drop(?:ped|ping|s)?|minimi[sz]\w*)\b"
    ),
    "increase": (
        r"\b(?:increas\w*|rais(?:e|ed|es|ing)|improv\w*|boost\w*|grew|grow\w*|enhanc\w*"
        r"|accelerat\w*|sped|speed(?:s|ing)?\s+up|faster|quicker|higher|expand\w*"
        r"|maximi[sz]\w*|strengthen\w*)\b"
    ),
    "save": r"\bsav(?:e|ed|es|ing|ings)\b",
}
_HEDGE_RE = re.compile(
    r"\b(?:help(?:ed|ing|s)?|assist\w*|contribut\w*|participat\w*|involved\s+in)\b",
    re.IGNORECASE,
)
_FREQUENCIES: dict[str, str] = {
    "hour": r"\b(?:hourly|an\s+hour|per\s+hour|each\s+hour|every\s+hour)\b",
    "day": r"\b(?:daily|a\s+day|per\s+day|each\s+day|every\s+day)\b|/day\b",
    "night": r"\b(?:nightly|a\s+night|per\s+night|each\s+night|every\s+night|overnight)\b",
    "week": r"\b(?:weekly|a\s+week|per\s+week|each\s+week|every\s+week)\b|/week\b",
    "fortnight": r"\b(?:biweekly|bi-weekly|fortnightly)\b",
    "month": r"\b(?:monthly|a\s+month|per\s+month|each\s+month|every\s+month)\b|/month\b",
    "quarter": r"\b(?:quarterly|a\s+quarter|per\s+quarter|each\s+quarter|every\s+quarter)\b",
    "year": (
        r"\b(?:yearly|annually|annual|a\s+year|per\s+year|per\s+annum|each\s+year"
        r"|every\s+year)\b|/(?:year|yr)\b"
    ),
}


def _compile(table: dict[str, str]) -> dict[str, re.Pattern[str]]:
    return {key: re.compile(pattern, re.IGNORECASE) for key, pattern in table.items()}


_LEADERSHIP_RES = _compile(_LEADERSHIP)
_ABSOLUTE_RES = _compile(_ABSOLUTES)
_RESULT_RES = _compile(_RESULTS)
_QUALIFIER_RES = _compile(_QUALIFIERS)
_FREQUENCY_RES = _compile(_FREQUENCIES)


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


@dataclass
class _Fact:
    kind: FactKind
    start: int
    end: int
    text: str
    reason: str


_PRIORITY = {
    FactKind.NUMBER: 0,
    FactKind.DATE: 0,
    FactKind.CERTIFICATION: 1,
    FactKind.SKILL: 2,
    FactKind.NAME: 3,
    FactKind.SCOPE: 4,
    FactKind.LENGTH: 5,
}


def _clean(text: str) -> str:
    text = strip_bullet(normalize(text))[0]
    return text.strip().strip("\"'\u201c\u201d").strip()


def _within(inner: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(start <= inner[0] and inner[1] <= end for start, end in spans)


def _overlaps(inner: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(inner[0] < end and start < inner[1] for start, end in spans)


def check_rewrite(
    source: str, rewrite: str, catalog: SkillCatalog | None = None
) -> FactCheckResult:
    """Pass or fail, and every fact the rewrite adds to the source."""
    catalog = catalog or get_catalog()
    source = _clean(source)
    rewrite = _clean(rewrite)
    facts: list[_Fact] = []

    def add(kind: FactKind, start: int, end: int, reason: str, text: str | None = None) -> None:
        facts.append(_Fact(kind, start, end, text or rewrite[start:end], reason))

    if not rewrite:
        return FactCheckResult(
            passed=False,
            added=(AddedFact(FactKind.LENGTH, "", "The rewrite is empty."),),
        )
    if len(rewrite) > 2 * len(source) + 20:
        add(
            FactKind.LENGTH,
            0,
            0,
            "The rewrite is more than twice as long as the original line, which usually "
            "means it adds content.",
            text="",
        )

    # Numbers and years.
    source_quantities = _quantities(source)
    rewrite_quantities = _quantities(rewrite)
    for quantity in rewrite_quantities:
        if _supported(quantity, source_quantities):
            continue
        words = rewrite[quantity.start : quantity.end]
        if quantity.is_year:
            add(
                FactKind.DATE,
                quantity.start,
                quantity.end,
                f'The date "{words}" isn\'t in the original line.',
            )
        else:
            add(
                FactKind.NUMBER,
                quantity.start,
                quantity.end,
                f'The number "{words}" isn\'t in the original line.',
            )
    quantity_spans = [(q.start, q.end) for q in rewrite_quantities]

    # Other dates.
    source_dates = {m.group().lower()[:3] for m in _MONTH_RE.finditer(source)}
    source_dates |= {m.group().upper().replace(" ", "") for m in _PERIOD_RE.finditer(source)}
    date_spans: list[tuple[int, int]] = []
    for found in _MONTH_RE.finditer(rewrite):
        date_spans.append(found.span())
        if found.group().lower()[:3] not in source_dates:
            add(
                FactKind.DATE,
                *found.span(),
                f'The date "{found.group()}" isn\'t in the original line.',
            )
    for found in _PERIOD_RE.finditer(rewrite):
        date_spans.append(found.span())
        if found.group().upper().replace(" ", "") not in source_dates:
            add(
                FactKind.DATE,
                *found.span(),
                f'The date "{found.group()}" isn\'t in the original line.',
            )

    source_tokens = _source_tokens(source)
    source_words = _content_words(source)

    # Catalog terms equivalent to a term the source uses for the same skill. Spelling
    # out any other acronym in capitalized words isn't accepted: the checker can't
    # tell "Azure Kubernetes Service" for "AKS" from "Acme Web Solutions" for "AWS".
    accepted: list[tuple[int, int]] = []

    source_hits = catalog.find(source)
    source_terms: dict[str, list[str]] = {}
    for hit in source_hits:
        source_terms.setdefault(hit.skill, []).append(hit.term)

    def vendor_ok(word: str, end: int) -> bool:
        """A vendor name is allowed only directly before a product of that vendor
        that the source names: "Amazon Redshift" for "Redshift". On its own ("at
        Amazon", "on AWS") it is a new organization or skill."""
        products = _VENDOR_PRODUCTS.get(word.lower())
        following = re.match(r"\s+([A-Za-z0-9][A-Za-z0-9.#+]*)", rewrite[end:])
        if products is None or following is None:
            return False
        product = _norm(following.group(1))
        return product in products and product in source_tokens

    for hit in catalog.find(rewrite):
        span = (hit.start, hit.end)
        terms = source_terms.get(hit.skill)
        if terms is not None:
            if any(
                _variant(hit.term, term)
                or _descriptive(hit.term)
                or _descriptive(term)
                or _acronym_of(hit.term, term)
                or _acronym_of(term, hit.term)
                for term in terms
            ):
                accepted.append(span)
            continue
        if vendor_ok(hit.term, hit.end):
            accepted.append(span)
            continue
        add(
            FactKind.SKILL,
            hit.start,
            hit.end,
            f"Names {hit.skill}, which the original line doesn't mention.",
        )

    # Capitalized names. Neighbouring flagged words are reported as one name.
    name_runs: list[list[re.Match[str]]] = []
    previous_end = -1
    for token in _TOKEN_RE.finditer(rewrite):
        word = token.group().rstrip(".")
        span = (token.start(), token.start() + len(word))
        if not _name_like(word) or word == "I":
            continue
        if _overlaps(span, quantity_spans) or _overlaps(span, date_spans):
            continue
        if _within(span, accepted):
            continue
        forms = _forms(word)
        if forms & source_tokens:
            continue
        at_start = not rewrite[: token.start()].strip() or bool(
            _SENTENCE_END.search(rewrite[: token.start()])
        )
        if at_start and word[0].isupper() and word[1:].islower():
            lower = word.lower()
            if lower in _COMMON_STARTS or lower.endswith(("ed", "ing", "ly")):
                continue
        if _is_acronym(word) and _initials_match(source_words, _acronym_letters(word)):
            continue
        if vendor_ok(word, span[1]):
            continue
        gap = rewrite[previous_end : token.start()] if previous_end >= 0 else None
        if name_runs and gap is not None and not gap.strip():
            name_runs[-1].append(token)
        else:
            name_runs.append([token])
        previous_end = span[1]
    for run in name_runs:
        start = run[0].start()
        end = run[-1].start() + len(run[-1].group().rstrip("."))
        name = re.sub(r"['\u2019]s$", "", rewrite[start:end])
        add(
            FactKind.NAME,
            start,
            end,
            f'"{name}" looks like the name of an organization or '
            "product that isn't in the original line.",
            text=name,
        )

    # Certifications.
    source_certs = {m.group().lower() for m in _CERT_RE.finditer(source)}
    for found in _CERT_RE.finditer(rewrite):
        if found.group().lower() in source_certs:
            continue
        start, end = found.span()
        # Widen to the certification's name: "AWS Certified Developer".
        while (before := re.search(r"([A-Z][\w.+#]*)[\s-]$", rewrite[:start])) is not None:
            start = before.start(1)
        while (after := re.match(r"[\s-]([A-Z][\w.+#]*)", rewrite[end:])) is not None:
            end += after.end()
        while end > start and rewrite[end - 1] in ".,;:":
            end -= 1
        add(
            FactKind.CERTIFICATION,
            start,
            end,
            f'"{rewrite[start:end]}" claims a certification the original line doesn\'t mention.',
        )

    # Frequencies, then scope words outside them ("every day" is a frequency).
    frequency_spans: list[tuple[int, int]] = []
    for pattern in _FREQUENCY_RES.values():
        for found in pattern.finditer(rewrite):
            frequency_spans.append(found.span())
            if not pattern.search(source):
                add(
                    FactKind.NUMBER,
                    *found.span(),
                    f'"{found.group()}" adds a frequency the original line doesn\'t state.',
                )
    masked_rewrite = _mask(rewrite, frequency_spans)
    masked_source = _mask(
        source, [m.span() for p in _FREQUENCY_RES.values() for m in p.finditer(source)]
    )

    scope_checks = [
        (_LEADERSHIP_RES, "claims more responsibility than the original line does."),
        (_ABSOLUTE_RES, "widens the claim beyond what the original line says."),
        (_QUALIFIER_RES, "describes the work in a way the original line doesn't."),
        (_RESULT_RES, "adds a result the original line doesn't state."),
    ]
    for table, explanation in scope_checks:
        for pattern in table.values():
            scope_hit = pattern.search(masked_rewrite)
            if scope_hit is not None and not pattern.search(masked_source):
                add(FactKind.SCOPE, *scope_hit.span(), f'"{scope_hit.group()}" {explanation}')
    hedge = _HEDGE_RE.search(source)
    if hedge is not None and not _HEDGE_RE.search(rewrite):
        add(
            FactKind.SCOPE,
            0,
            0,
            f'The rewrite drops "{hedge.group()}", which makes the person\'s part sound bigger.',
            text=hedge.group(),
        )

    # One fact per phrase: drop a fact that sits inside a higher-priority one.
    facts.sort(key=lambda f: (_PRIORITY[f.kind], f.start))
    kept: list[_Fact] = []
    for fact in facts:
        if fact.end > fact.start and any(
            other.start <= fact.start
            and fact.end <= other.end
            and _PRIORITY[other.kind] < _PRIORITY[fact.kind]
            for other in kept
        ):
            continue
        if any(other.text == fact.text and other.kind == fact.kind for other in kept):
            continue
        kept.append(fact)
    kept.sort(key=lambda f: (f.start, _PRIORITY[f.kind]))
    added = tuple(AddedFact(f.kind, f.text, f.reason) for f in kept)
    return FactCheckResult(passed=not added, added=added)
