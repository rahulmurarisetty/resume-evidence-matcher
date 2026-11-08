"""Degree and certification requirements, checked against the education and
certification lines of the resume.

"Bachelor's degree in Computer Science or a related field", "Master's preferred" and
"AWS Certified Solutions Architect" ask for a credential, not a skill used at work,
so they are decided from the education entries and certification lines:

- direct when a degree at the asked level (or higher) in a named or clearly related
  field is listed, or a certification line names the asked certification;
- gap when it is clearly absent: no degree at that level, or no certification line
  that names the vendor or skill;
- not assessed (a person has to check) when the level is right but the field can't be
  judged, when only another certification from the same vendor is listed, or when the
  job accepts equivalent experience instead of a degree.

Everything here is rule based. A field the rules don't know is never guessed to match.
"""

import re
from dataclasses import dataclass, field
from enum import IntEnum

from app.models import (
    Evidence,
    EvidenceStrength,
    MatchStatus,
    Profile,
    ResumeDocument,
    Section,
    SkillMatch,
    Span,
    SpanKind,
)
from app.services.skills import SkillCatalog


class DegreeLevel(IntEnum):
    ASSOCIATE = 1
    BACHELOR = 2
    MASTER = 3
    DOCTORATE = 4


LEVEL_NAMES = {
    DegreeLevel.ASSOCIATE: "Associate degree",
    DegreeLevel.BACHELOR: "Bachelor's degree",
    DegreeLevel.MASTER: "Master's degree",
    DegreeLevel.DOCTORATE: "Doctorate",
}

# ---------------------------------------------------------------------------
# Degree levels, in job descriptions and in resumes
# ---------------------------------------------------------------------------

_APOS = r"['\u2019]?"
# In a job description. "MS" and "BS" count only next to "/", "or", "in" or
# "degree", so "MS Excel" and "MS SQL" aren't degrees.
_ASK_LEVELS: list[tuple[DegreeLevel, re.Pattern[str]]] = [
    (
        DegreeLevel.DOCTORATE,
        re.compile(r"\bph\.?\s?d\b\.?|\bdoctorate\b|\bdoctoral\b|\bdoctor of\b", re.IGNORECASE),
    ),
    (
        DegreeLevel.MASTER,
        re.compile(
            rf"\bmaster{_APOS}s\b|\bmasters\b|\bmaster(?=\s+(?:of|degree|in)\b)"
            r"|\bm\.\s?s\.|\bm\.\s?sc\b|\bmsc\b"
            r"|\bm\.?\s?tech\b|\bm\.\s?e\.|\bmeng\b|\bm\.?b\.?a\b|\bmca\b"
            r"|\bms\b(?=\s*(?:/|or\b|in\b|degree\b|,))|(?<=/)\s*ms\b"
            r"|\bgraduate degree\b|\bpost-?graduate\b|\badvanced degree\b",
            re.IGNORECASE,
        ),
    ),
    (
        DegreeLevel.BACHELOR,
        re.compile(
            rf"\bbachelors?{_APOS}s?\b|\bb\.\s?s\.|\bb\.\s?sc\b|\bbsc\b|\bb\.\s?a\.|\bb\.?\s?tech\b"
            r"|\bb\.\s?e\.|\bbeng\b|\bbba\b|\bbca\b"
            r"|\bbs\b(?=\s*(?:/|or\b|in\b|degree\b|,))|\bba\b(?=\s*(?:/|or\b|in\b|degree\b))"
            r"|\bundergraduate degree\b|\b(?:four|4)[\s-]year degree\b"
            r"|\b(?:college|university) degree\b",
            re.IGNORECASE,
        ),
    ),
    (
        DegreeLevel.ASSOCIATE,
        re.compile(rf"\bassociates?{_APOS}s?\s+(?:degree|of)\b", re.IGNORECASE),
    ),
]
# "A degree in Computer Science" with no level reads as a bachelor's degree.
_PLAIN_DEGREE = re.compile(
    r"\b(?:a|an|the|relevant|related|technical|any)\s+degree\b|\bdegree\s+in\b"
    r"|\bdegree\s+(?:required|preferred)\b|\bdegreed?\b(?=\s+(?:or|and)\s+equivalent)",
    re.IGNORECASE,
)

# In a resume's education line.
_HAS_LEVELS: list[tuple[DegreeLevel, re.Pattern[str]]] = [
    (
        DegreeLevel.DOCTORATE,
        re.compile(r"\bph\.?\s?d\b|\bdoctor(?:ate| of)\b|\bd\.?\s?phil\b|\bed\.d\b", re.IGNORECASE),
    ),
    (
        DegreeLevel.MASTER,
        re.compile(
            r"\bmaster|\bm\.?\s?(?:s|a|sc|e|eng|tech|com|ed|phil|ca|ph|ba)\b\.?|\bmsc\b"
            r"|\bmtech\b|\bmeng\b|\bmba\b|\bm\.b\.a\b|\bmca\b|\bllm\b",
            re.IGNORECASE,
        ),
    ),
    (
        DegreeLevel.BACHELOR,
        re.compile(
            r"\bbachelor|\bb\.?\s?(?:s|a|sc|e|eng|tech|com|ed|ba|ca|arch)\b\.?|\bbsc\b"
            r"|\bbtech\b|\bbeng\b|\bbba\b|\bbca\b|\bllb\b",
            re.IGNORECASE,
        ),
    ),
    (
        DegreeLevel.ASSOCIATE,
        re.compile(r"\bassociate\b|\ba\.\s?(?:s|a|as)\.", re.IGNORECASE),
    ),
]
_ENGINEERING_DEGREE = re.compile(
    r"\b(?:b|m)\.?\s?(?:tech|e|eng)\b\.?|\bbtech\b|\bmtech\b|\bbeng\b|\bmeng\b"
    r"|\bof engineering\b",
    re.IGNORECASE,
)
_BUSINESS_DEGREE = re.compile(r"\bm\.?b\.?a\b|\bbba\b|\bof business\b|\bof commerce\b", re.I)
_COMPUTING_DEGREE = re.compile(r"\b(?:bca|mca)\b|\bcomputer applications\b", re.IGNORECASE)


def degree_level(text: str) -> DegreeLevel | None:
    """The highest degree level an education line names."""
    for level, pattern in _HAS_LEVELS:
        if pattern.search(text):
            return level
    return None


# ---------------------------------------------------------------------------
# Fields of study
# ---------------------------------------------------------------------------

_FAMILY_WORDS: dict[str, tuple[str, ...]] = {
    "computing": (
        "computer",
        "computing",
        "software",
        "information technology",
        "information systems",
        "information science",
        "informatics",
        "data science",
        "cybersecurity",
        "cyber security",
        "computer applications",
        "artificial intelligence",
        "machine learning",
    ),
    "engineering": (
        "engineering",
        "electronics",
        "electrical",
        "mechanical",
        "civil",
        "chemical",
        "industrial",
        "aerospace",
        "instrumentation",
        "mechatronics",
        "telecommunication",
    ),
    "quantitative": (
        "mathematics",
        "math",
        "maths",
        "statistics",
        "statistical",
        "physics",
        "economics",
        "econometrics",
        "operations research",
        "actuarial",
        "finance",
        "quantitative",
        "data science",
        "analytics",
        "biostatistics",
    ),
    "science": (
        "science",
        "biology",
        "chemistry",
        "biochemistry",
        "neuroscience",
        "geology",
        "bioinformatics",
    ),
    "business": (
        "business",
        "management",
        "administration",
        "finance",
        "accounting",
        "economics",
        "marketing",
        "commerce",
    ),
}
# What a family word in a job description accepts.
_ASKED_FAMILIES: dict[str, set[str]] = {
    "quantitative": {"quantitative", "computing", "engineering"},
    "technical": {"computing", "engineering", "quantitative", "science"},
    "stem": {"computing", "engineering", "quantitative", "science"},
    "scientific": {"computing", "engineering", "quantitative", "science"},
    "engineering": {"engineering", "computing"},
    "computer": {"computing"},
    "computing": {"computing"},
    "business": {"business"},
}
_ABBREVIATIONS = {
    "cs": "computer science",
    "it": "information technology",
    "ee": "electrical engineering",
    "ece": "electronics and communication engineering",
    "mis": "management information systems",
    "math": "mathematics",
    "maths": "mathematics",
    "stats": "statistics",
    "econ": "economics",
}
_FIELD_FILLER = re.compile(
    r"\b(?:a|an|the|other|any|field|fields|discipline|disciplines|area|areas|subject|major"
    r"|program|degree|degrees|study|of|equivalent|similar|relevant|related|closely"
    r"|preferably|ideally|e\.g|such as|like)\b",
    re.IGNORECASE,
)
_RELATED_WORD = re.compile(r"\b(?:related|similar|relevant|equivalent|comparable)\b", re.I)
_FAMILY_ASK = re.compile(
    r"\b(quantitative|technical|stem|scientific|engineering|computer|computing|business)"
    r"\s+(?:or\s+\w+\s+)?(?:field|fields|discipline|disciplines|area|areas|degree|subject)\b",
    re.IGNORECASE,
)
_EXPERIENCE_INSTEAD = re.compile(
    r"\bor\s+(?:the\s+)?equivalent\s+(?:practical\s+|professional\s+|work\s+|combination\s+of\s+"
    r"education\s+and\s+)?(?:experience|work)\b|\bequivalent\s+(?:work\s+|practical\s+)?"
    r"experience\b|\bor\s+(?:\d+\+?\s+years|relevant experience)\b",
    re.IGNORECASE,
)
_FIELD_PHRASE = re.compile(
    r"\b(?:degree|bachelor\S*|master\S*|ph\.?\s?d\.?|doctorate|b\.?\s?s\.?|m\.?\s?s\.?"
    r"|b\.?\s?a\.?|m\.?\s?a\.?|mba|b\.?\s?tech|m\.?\s?tech|bs/ms|ms/phd|b\.?\s?sc|m\.?\s?sc)"
    r"(?:[^.;:()]*?)\s+in\s+(?P<fields>[^.;:()]+)",
    re.IGNORECASE,
)
_FIELD_END = re.compile(
    r"\s+(?:and|with|plus)\s+(?:\d|at least|a minimum|minimum|experience|strong|proven"
    r"|hands-on|knowledge)|\s*,?\s*(?:and/)?or\s+(?:the\s+)?equivalent\b"
    r"|\s+(?:is|are)\s+(?:required|preferred|a plus)|\s+(?:required|preferred)\b"
    r"|\s+from\s+an?\s+",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z&-]*", text.lower())
    expanded: list[str] = []
    for word in words:
        expanded.extend(_ABBREVIATIONS.get(word, word).split())
    return expanded


def _families(field_text: str) -> set[str]:
    text = " ".join(_words(field_text))
    return {
        family
        for family, words in _FAMILY_WORDS.items()
        if any(re.search(rf"\b{re.escape(w)}", text) for w in words)
    }


def _field_matches(asked: str, degree_field: str) -> bool:
    """Is the degree's field the asked one? "Computer Science" matches "B.S. Computer
    Science" and "Computer Science and Engineering"."""
    asked_words = [w for w in _words(asked) if w not in {"and", "&"}]
    have = set(_words(degree_field))
    return bool(asked_words) and all(w in have or w.rstrip("s") in have for w in asked_words)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

_CERT_WORD = re.compile(
    r"\bcertif(?:ied|ication|ications|icate|icates)\b(?!\s+(?:of|process|testing|management"
    r"|authority|authorities|rotation|pinning|renewal))",
    re.IGNORECASE,
)
_NOT_A_CREDENTIAL = re.compile(
    r"\b(?:ssl|tls|x\.?509|digital|code[\s-]signing|server|client)\s+certificates?\b",
    re.IGNORECASE,
)
_CERT_ACRONYMS = re.compile(
    r"\b(?:CKA|CKAD|CKS|PMP|CAPM|CISSP|CISM|CISA|CEH|OSCP|CCNA|CCNP|CCIE|CSM|CSPO|PSM|PSPO"
    r"|CPA|CFA|FRM|RHCE|RHCSA|MCSE|MCSA|ISTQB|CompTIA|CPCU|AINS|CPIA|CSSLP|GCP-?ACE"
    r"|(?:AZ|DP|AI|PL|SC|MS)-\d{3}|SAA-C0\d|Security\+|Network\+|A\+)(?![\w+])"
)
_ANY_CERT = re.compile(
    r"\bor\s+(?:a\s+|an\s+|other\s+|any\s+)?(?:similar|equivalent|comparable|related|relevant"
    r"|other)\b|\bany\b|\brelevant\b|\bsuch as\b|\be\.g\b|\bindustry\b",
    re.IGNORECASE,
)
_GENERIC_WORDS = {
    "certified",
    "certification",
    "certifications",
    "certificate",
    "certificates",
    "preferred",
    "required",
    "plus",
    "similar",
    "equivalent",
    "strongly",
    "highly",
    "must",
    "have",
    "active",
    "current",
    "valid",
    "industry",
    "relevant",
    "related",
    "such",
    "as",
    "is",
    "are",
    "a",
    "an",
    "the",
    "one",
    "any",
    "following",
    "other",
    "in",
    "of",
    "for",
    "with",
    "and",
    "experience",
    "knowledge",
    "ideally",
    "bonus",
    "nice",
    "desired",
    "desirable",
}


@dataclass(frozen=True)
class _CertGroup:
    """One alternative: "AWS Certified Solutions Architect" is the keys {AWS} and
    the title words ("Solutions", "Architect")."""

    keys: frozenset[str]
    titles: tuple[str, ...]


@dataclass(frozen=True)
class CredentialAsk:
    kind: str  # "degree" or "certification"
    name: str  # "Master's degree", "Kubernetes certification"
    level: DegreeLevel | None = None
    fields: tuple[str, ...] = ()
    families: frozenset[str] = frozenset()
    related_ok: bool = False
    experience_ok: bool = False
    field_span: tuple[int, int] | None = None
    keys: frozenset[str] = frozenset()
    groups: tuple[_CertGroup, ...] = ()
    any_cert: bool = False


def _degree_ask(text: str) -> CredentialAsk | None:
    levels = [level for level, pattern in _ASK_LEVELS if pattern.search(text)]
    if not levels:
        if not _PLAIN_DEGREE.search(text):
            return None
        levels = [DegreeLevel.BACHELOR]
    level = min(levels)
    fields: list[str] = []
    families: set[str] = set()
    related_ok = False
    span: tuple[int, int] | None = None
    found = _FIELD_PHRASE.search(text)
    if found is not None:
        phrase = found.group("fields")
        end = _FIELD_END.search(phrase)
        if end is not None:
            phrase = phrase[: end.start()]
        span = (found.start("fields"), found.start("fields") + len(phrase))
        related_ok = bool(_RELATED_WORD.search(phrase))
        for asked in _FAMILY_ASK.finditer(phrase):
            families |= _ASKED_FAMILIES[asked.group(1).lower()]
        phrase = _FAMILY_ASK.sub(" ", phrase)
        for part in re.split(r",|/|\bor\b|\band\b|&", phrase):
            name = re.sub(r"\s+", " ", _FIELD_FILLER.sub(" ", part)).strip(" .-")
            if name and _words(name):
                fields.append(name)
    elif (named_family := _FAMILY_ASK.search(text)) is not None:
        families |= _ASKED_FAMILIES[named_family.group(1).lower()]
    return CredentialAsk(
        kind="degree",
        name=LEVEL_NAMES[level],
        level=level,
        fields=tuple(fields),
        families=frozenset(families),
        related_ok=related_ok,
        experience_ok=bool(_EXPERIENCE_INSTEAD.search(text)),
        field_span=span,
    )


def _cert_ask(text: str, catalog: SkillCatalog) -> CredentialAsk | None:
    if _NOT_A_CREDENTIAL.search(text):
        return None
    acronyms = list(_CERT_ACRONYMS.finditer(text))
    if not _CERT_WORD.search(text) and not acronyms:
        return None
    keyed: list[tuple[int, int, str]] = [(h.start, h.end, h.skill) for h in catalog.mentions(text)]
    keyed += [(m.start(), m.end(), m.group()) for m in acronyms]
    keys = frozenset(name for _, _, name in keyed)

    # Split the text into alternatives at "or", "/" and commas, keeping the keys and
    # the capitalized title words of each.
    groups: list[_CertGroup] = []
    group_keys: set[str] = set()
    titles: list[str] = []
    for token in re.finditer(r"[A-Za-z][A-Za-z0-9+&.-]*|/|,|\(|\)", text):
        word = token.group()
        if word in {"/", ","} or word.lower() == "or":
            groups.append(_CertGroup(frozenset(group_keys), tuple(titles)))
            group_keys, titles = set(), []
            continue
        inside = [name for start, end, name in keyed if start <= token.start() < end]
        if inside:
            group_keys.update(inside)
        elif word[:1].isupper() and word.lower().rstrip(".") not in _GENERIC_WORDS:
            titles.append(word.rstrip("."))
    groups.append(_CertGroup(frozenset(group_keys), tuple(titles)))
    groups = [g for g in groups if g.keys or g.titles]

    named = sorted(keys, key=lambda k: min(s for s, _, n in keyed if n == k))
    name = f"{named[0]} certification" if named else "Certification"
    return CredentialAsk(
        kind="certification",
        name=name,
        keys=keys,
        groups=tuple(groups),
        any_cert=bool(_ANY_CERT.search(text)) or not keys,
    )


def credential_ask(text: str, catalog: SkillCatalog) -> CredentialAsk | None:
    """The degree or certification a requirement asks for, or None."""
    return _degree_ask(text) or _cert_ask(text, catalog)


# ---------------------------------------------------------------------------
# Matching against the resume
# ---------------------------------------------------------------------------


@dataclass
class CredentialResult:
    status: MatchStatus
    skill: SkillMatch
    action: str
    other_skills: list[str] = field(default_factory=list)


def _evidence(span: Span, term: str) -> Evidence:
    return Evidence(
        span_id=span.id,
        text=span.text,
        section=span.section,
        page=span.page,
        matched_term=term,
        strength=EvidenceStrength.DEMONSTRATED,
    )


def _quote(text: str) -> str:
    return f'"{text}"'


_COMMON_NAME_WORDS = {"Bachelor's", "Master's", "Associate", "Doctorate", "Certification", "Degree"}


def with_article(name: str) -> str:
    """ "an ISTQB certification", "a Kubernetes certification", "a master's degree"."""
    first = name.split()[0] if name.split() else name
    if len(first) > 1 and first.isupper():
        vowel_sound = first[0] in "AEFHILMNORSX"  # how the letter's name sounds
    else:
        vowel_sound = first[:1].lower() in "aeiou"
    shown = name[:1].lower() + name[1:] if first in _COMMON_NAME_WORDS else name
    return f"{'an' if vowel_sound else 'a'} {shown}"


class CredentialContext:
    """What the resume shows about degrees and certifications."""

    def __init__(self, resume: ResumeDocument, profile: Profile, catalog: SkillCatalog) -> None:
        self.catalog = catalog
        self.profile = profile
        self._spans = {span.id: span for span in resume.spans}
        self._cert_lines = [
            span
            for span in resume.spans
            if span.kind is not SpanKind.HEADING
            and (
                span.section is Section.CERTIFICATIONS
                or (
                    span.section is not Section.EXPERIENCE
                    and (_CERT_WORD.search(span.text) or _CERT_ACRONYMS.search(span.text))
                )
            )
        ]

    def ask(self, text: str) -> CredentialAsk | None:
        return credential_ask(text, self.catalog)

    def other_skills(self, text: str, ask: CredentialAsk) -> list[str]:
        """Catalog skills the requirement names besides the credential: "Java" in
        "Bachelor's degree in Computer Science and 3+ years of Java". The field of
        study and the certification's own vendor or skill don't count."""
        if ask.kind == "certification":
            return []
        if ask.field_span is not None:
            start, end = ask.field_span
            text = f"{text[:start]} {' ' * (end - start)} {text[end:]}"
        return self.catalog.requirement_skills(text)

    def match(self, ask: CredentialAsk) -> CredentialResult:
        if ask.kind == "degree":
            return self._match_degree(ask)
        return self._match_cert(ask)

    # -- degrees ---------------------------------------------------------------

    def _degree_field(self, degree: str) -> tuple[str, set[str]]:
        """The field of a degree line and its families: "B.Tech Electronics" is
        ("Electronics", {"engineering"})."""
        families = _families(degree)
        if _ENGINEERING_DEGREE.search(degree):
            families.add("engineering")
        if _BUSINESS_DEGREE.search(degree):
            families.add("business")
        if _COMPUTING_DEGREE.search(degree):
            families.add("computing")
        return degree, families

    def _match_degree(self, ask: CredentialAsk) -> CredentialResult:
        assert ask.level is not None
        name = ask.name
        entries = self.profile.education
        missing = SkillMatch(skill=name, strength=None, evidence=[])
        if not entries:
            if ask.experience_ok:
                return CredentialResult(
                    MatchStatus.NOT_ASSESSED,
                    missing,
                    f"Asks for {with_article(name)} or equivalent experience. No education was "
                    "found in the resume, so check whether your experience counts. If you "
                    "have a degree, add an education section.",
                )
            return CredentialResult(
                MatchStatus.GAP,
                missing,
                f"Asks for {with_article(name)}. No education was found in the resume. If you "
                "have a degree, add it in an education section with the school and year.",
            )

        unread = False
        level_met: list[tuple[str, list[Span]]] = []
        for entry in entries:
            text = entry.degree or ""
            level = degree_level(text) if text else None
            spans = [self._spans[i] for i in entry.span_ids if i in self._spans]
            if level is None:
                unread = True
            elif level >= ask.level:
                level_met.append((text, spans))

        if not level_met:
            if unread or ask.experience_ok:
                reason = (
                    "or equivalent experience. Check whether your experience counts"
                    if ask.experience_ok
                    else "and the level of a degree in your resume couldn't be read. "
                    "Check it yourself"
                )
                return CredentialResult(
                    MatchStatus.NOT_ASSESSED, missing, f"Asks for {with_article(name)} {reason}."
                )
            return CredentialResult(
                MatchStatus.GAP,
                missing,
                f"Asks for {with_article(name)}, and the degrees in your resume are at a lower "
                "level. Don't change how a degree is named. If you have one that isn't "
                "listed, add it with the school and year.",
            )

        def proven(degree: str) -> bool:
            if not ask.fields and not ask.families:
                return True
            field_text, families = self._degree_field(degree)
            if any(_field_matches(f, field_text) for f in ask.fields):
                return True
            accepted = set(ask.families)
            if ask.related_ok:
                for asked in ask.fields:
                    accepted |= _families(asked)
            return bool(accepted & families)

        for degree, spans in level_met:
            if proven(degree) and spans:
                return CredentialResult(
                    MatchStatus.DIRECT,
                    SkillMatch(
                        skill=name,
                        strength=EvidenceStrength.DEMONSTRATED,
                        evidence=[_evidence(span, degree) for span in spans],
                    ),
                    f"Shown by your education: {_quote(degree)}.",
                )
        degree, spans = level_met[0]
        wanted = (" or ".join(ask.fields) if ask.fields else "the field the job asks for") + (
            " or a related field" if ask.related_ok else ""
        )
        return CredentialResult(
            MatchStatus.NOT_ASSESSED,
            SkillMatch(
                skill=name,
                strength=EvidenceStrength.DEMONSTRATED,
                evidence=[_evidence(span, degree) for span in spans],
            ),
            f"Asks for {with_article(name)} in {wanted}. Your resume lists {_quote(degree)}, and "
            "whether that field counts is for you or the employer to judge.",
        )

    # -- certifications ----------------------------------------------------------

    def _mentions(self, span: Span, keys: frozenset[str]) -> set[str]:
        found = {hit.skill for hit in self.catalog.mentions(span.text)}
        found |= {m.group() for m in _CERT_ACRONYMS.finditer(span.text)}
        return found & keys

    def _match_cert(self, ask: CredentialAsk) -> CredentialResult:
        missing = SkillMatch(skill=ask.name, strength=None, evidence=[])
        if not ask.keys:
            # "Relevant certifications are a plus": a person decides which count.
            if not self._cert_lines:
                return CredentialResult(
                    MatchStatus.GAP,
                    missing,
                    "Asks for a certification, and none is listed in the resume. Add one only "
                    "if you hold it, with its full name and year.",
                )
            line = self._cert_lines[0]
            return CredentialResult(
                MatchStatus.NOT_ASSESSED,
                SkillMatch(
                    skill=ask.name,
                    strength=EvidenceStrength.DEMONSTRATED,
                    evidence=[_evidence(s, s.text) for s in self._cert_lines[:5]],
                ),
                f"Asks for a certification without naming one. Your resume lists "
                f"{_quote(line.text)}. Check whether it is the kind the job means.",
            )

        candidates = [(span, self._mentions(span, ask.keys)) for span in self._cert_lines]
        candidates = [(span, keys) for span, keys in candidates if keys]
        if not candidates:
            return CredentialResult(
                MatchStatus.GAP,
                missing,
                f"Asks for {with_article(ask.name)}, and no certification line in the resume "
                "names it. Add it only if you hold it, with its full name and year.",
            )

        def satisfies(span: Span, keys: set[str]) -> bool:
            if ask.any_cert:
                return True
            text = span.text.lower()
            for group in ask.groups:
                group_keys = group.keys or ask.keys
                if not keys & group_keys:
                    continue
                if all(title.lower() in text for title in group.titles):
                    return True
            return False

        shown = [span for span, keys in candidates if satisfies(span, keys)]
        if shown:
            return CredentialResult(
                MatchStatus.DIRECT,
                SkillMatch(
                    skill=ask.name,
                    strength=EvidenceStrength.DEMONSTRATED,
                    evidence=[_evidence(span, span.text) for span in shown[:5]],
                ),
                f"Shown by your certification: {_quote(shown[0].text)}.",
            )
        line = candidates[0][0]
        return CredentialResult(
            MatchStatus.NOT_ASSESSED,
            SkillMatch(
                skill=ask.name,
                strength=EvidenceStrength.DEMONSTRATED,
                evidence=[_evidence(span, span.text) for span, _ in candidates[:5]],
            ),
            f"Asks for a specific certification. Your resume lists {_quote(line.text)}, which "
            "may be a different one. Check that it is the one the job names.",
        )


def combine(statuses: list[MatchStatus]) -> MatchStatus:
    """One status for a requirement with several parts ("a degree and 5+ years")."""
    unique = set(statuses)
    if unique == {MatchStatus.DIRECT}:
        return MatchStatus.DIRECT
    if unique == {MatchStatus.GAP}:
        return MatchStatus.GAP
    if unique <= {MatchStatus.DIRECT, MatchStatus.NOT_ASSESSED}:
        return MatchStatus.NOT_ASSESSED
    return MatchStatus.PARTIAL
