"""Questions for the person: one gap question per gap or adjacent requirement, and
metric questions for experience bullets that have no measurable result.

They are built from the report (and, for metric questions, the lines the app
read), with no model call, so the same analysis always gets the same questions.
The person's answers are stored with the analysis and never put into the resume:
the app never fills in a number.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.models import (
    AnalysisReport,
    EvidenceStrength,
    MatchMode,
    MatchStatus,
    Priority,
    RequirementMatch,
    ResumeDocument,
    Section,
    SpanKind,
)
from app.services.credentials import CredentialAsk, credential_ask, with_article
from app.services.skills import SkillCatalog, get_catalog

QUESTION_STATUSES = {MatchStatus.GAP, MatchStatus.ADJACENT}
# Statuses whose demonstrated evidence counts as support for a bullet.
SUPPORT_STATUSES = {MatchStatus.DIRECT, MatchStatus.PARTIAL}
MAX_METRIC_QUESTIONS = 5
METRIC_PREFIX = "metric-"
METRIC_ASK = "How many, how much, how fast or how often? Add a number only if you know it."
_MAX_QUOTE_CHARS = 140
_PRIORITY_ORDER = (Priority.REQUIRED, Priority.PREFERRED, Priority.CONTEXT)
# Numbers written as words, which the metric patterns don't read ("three engineers").
# A bullet with one already has a number, so it gets no metric question.
_NUMBER_WORDS = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty"
    r"|thirty|forty|fifty|hundreds?|thousands?|millions?|billions?|dozens?|half|twice"
    r"|double[ds]?|tripled?|halved)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GapQuestion:
    requirement_id: str | None
    requirement_text: str | None
    priority: Priority | None
    status: MatchStatus | None
    question: str
    kind: Literal["gap", "metric"] = "gap"
    span_id: str | None = None
    line: str | None = None

    @property
    def id(self) -> str:
        """The key answers are stored under: the requirement id for a gap question,
        "metric-<span id>" for a metric question."""
        if self.kind == "metric":
            return f"{METRIC_PREFIX}{self.span_id}"
        return self.requirement_id or ""


def _join(names: list[str], word: str) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {word} {names[-1]}"


def _quote(text: str) -> str:
    if len(text) > _MAX_QUOTE_CHARS:
        text = text[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return f'"{text}"'


def _ended(quote: str) -> str:
    """A quote that ends a sentence: a full stop after it unless the line has one."""
    return quote if quote[-2:-1] in (".", "!", "?") else f"{quote}."


def _ask_about(skills: list[str], mode: MatchMode, catalog: SkillCatalog) -> str:
    word = "or" if mode is MatchMode.ANY else "and"
    names = _join(skills, word)
    if all(catalog.categories.get(skill) == "domain" for skill in skills):
        return f"Have you worked in {names}? If yes, where, and what did you work on?"
    pronoun = "it" if len(skills) == 1 or mode is MatchMode.ANY else "them"
    return f"Have you used {names}? If yes, where, and what did you build with {pronoun}?"


def _ask_for_credential(ask: CredentialAsk) -> str:
    if ask.kind == "degree":
        field = f" in {' or '.join(ask.fields)}" if ask.fields else ""
        return (
            f"Do you have {with_article(ask.name)}{field}? If yes, add it to your education "
            "section with the school and the year."
        )
    return (
        f"Do you hold {with_article(ask.name)}? If yes, add it with its full name and the "
        "year you earned it."
    )


def question_for(match: RequirementMatch, catalog: SkillCatalog | None = None) -> str | None:
    """The question for one requirement, or None when it doesn't get one."""
    if match.status not in QUESTION_STATUSES:
        return None
    catalog = catalog or get_catalog()
    requirement = match.requirement
    missing = [m.skill for m in match.skills if m.strength is None]
    ask = credential_ask(requirement.text, catalog)
    if ask is not None and match.status is MatchStatus.GAP:
        return _ask_for_credential(ask)

    if match.status is MatchStatus.GAP:
        if requirement.min_years and not requirement.skills:
            return (
                f"The job asks for {requirement.min_years}+ years. Do you have earlier "
                "relevant work that isn't on your resume? If yes, give the employer, your "
                "title and the dates."
            )
        if missing:
            return _ask_about(missing, requirement.match_mode, catalog)
        return (
            f'Do you have experience with this: "{requirement.text}"? If yes, where, and '
            "what did you do?"
        )

    best = max(match.related_evidence, key=lambda r: r.score, default=None)
    line = f" This line looks related: {_quote(best.text)}." if best is not None else ""
    if missing:
        question = _ask_about(missing, requirement.match_mode, catalog)
        return f"{question.split('?', 1)[0]}?{line} If yes,{question.split('If yes,', 1)[1]}"
    return (
        f'Does your experience show this: "{requirement.text}"?{line} If yes, what exactly '
        "did you do?"
    )


def gap_questions(report: AnalysisReport, catalog: SkillCatalog | None = None) -> list[GapQuestion]:
    catalog = catalog or get_catalog()
    questions: list[GapQuestion] = []
    for match in report.matches:
        question = question_for(match, catalog)
        if question is not None:
            questions.append(
                GapQuestion(
                    requirement_id=match.requirement.id,
                    requirement_text=match.requirement.text,
                    priority=match.requirement.priority,
                    status=match.status,
                    question=question,
                )
            )
    return questions


def supported_requirements(
    matches: Sequence[RequirementMatch],
) -> dict[str, list[RequirementMatch]]:
    """For each resume line, the requirements it proves: it is demonstrated evidence
    of a direct or partial requirement. Required requirements come first, then
    preferred, then job duties, each in the job's order."""
    support: dict[str, list[RequirementMatch]] = {}
    for priority in _PRIORITY_ORDER:
        for match in matches:
            if match.requirement.priority is not priority or match.status not in SUPPORT_STATUSES:
                continue
            for skill in match.skills:
                for evidence in skill.evidence:
                    if evidence.strength is not EvidenceStrength.DEMONSTRATED:
                        continue
                    proven = support.setdefault(evidence.span_id, [])
                    if match not in proven:
                        proven.append(match)
    return support


def _experience_bullets(report: AnalysisReport, resume: ResumeDocument) -> list[str]:
    role_bullets = {
        span_id
        for role in report.profile.roles
        if role.section is Section.EXPERIENCE
        for span_id in role.bullet_span_ids
    }
    return [
        span.id
        for span in resume.spans
        if span.kind is SpanKind.BULLET
        and (span.section is Section.EXPERIENCE or span.id in role_bullets)
    ]


def metric_questions(
    report: AnalysisReport, resume: ResumeDocument, limit: int = MAX_METRIC_QUESTIONS
) -> list[GapQuestion]:
    """Up to `limit` questions about experience bullets with no measurable result.
    Bullets that support required requirements come first, then preferred, then
    job duties, then the rest, each in reading order."""
    with_metrics = set(report.profile.metric_bullets)
    support = supported_requirements(report.matches)
    texts = {span.id: span.text for span in resume.spans}

    def rank(span_id: str) -> tuple[int, ...]:
        proven = support.get(span_id, [])
        return tuple(-sum(m.requirement.priority is p for m in proven) for p in _PRIORITY_ORDER)

    candidates = [
        i
        for i in _experience_bullets(report, resume)
        if i not in with_metrics and not _NUMBER_WORDS.search(texts[i])
    ]
    # sorted() is stable, so equal ranks keep reading order.
    chosen = sorted(candidates, key=rank)[:limit]
    questions: list[GapQuestion] = []
    for span_id in chosen:
        proven = support.get(span_id, [])
        first = proven[0] if proven else None
        questions.append(
            GapQuestion(
                requirement_id=first.requirement.id if first else None,
                requirement_text=first.requirement.text if first else None,
                priority=first.requirement.priority if first else None,
                status=first.status if first else None,
                question=f"No number in this bullet: {_ended(_quote(texts[span_id]))} {METRIC_ASK}",
                kind="metric",
                span_id=span_id,
                line=texts[span_id],
            )
        )
    return questions


def all_questions(
    report: AnalysisReport,
    resume: ResumeDocument | None,
    catalog: SkillCatalog | None = None,
) -> list[GapQuestion]:
    """Gap questions, then metric questions. Without the resume lines (analyses from
    before v0.3) there are no metric questions."""
    questions = gap_questions(report, catalog)
    if resume is not None:
        questions += metric_questions(report, resume)
    return questions
