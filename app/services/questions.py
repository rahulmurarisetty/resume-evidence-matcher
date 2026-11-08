"""Gap questions: one plain question per gap or adjacent requirement.

They are built from the report alone, with no model call, so the same report
always gets the same questions. The person's answers are stored with the
analysis and never put into the resume.
"""

from dataclasses import dataclass

from app.models import (
    AnalysisReport,
    MatchMode,
    MatchStatus,
    Priority,
    RequirementMatch,
)
from app.services.credentials import CredentialAsk, credential_ask, with_article
from app.services.skills import SkillCatalog, get_catalog

QUESTION_STATUSES = {MatchStatus.GAP, MatchStatus.ADJACENT}
_MAX_QUOTE_CHARS = 140


@dataclass(frozen=True)
class GapQuestion:
    requirement_id: str
    requirement_text: str
    priority: Priority
    status: MatchStatus
    question: str


def _join(names: list[str], word: str) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {word} {names[-1]}"


def _quote(text: str) -> str:
    if len(text) > _MAX_QUOTE_CHARS:
        text = text[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return f'"{text}"'


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
