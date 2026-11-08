"""Section priority advice: where to move lines so the strongest evidence is read
first. It is deterministic and never changes the resume: the person decides.

Three kinds of advice:

- move_bullet_up: in each role, the bullets that prove the most required (then
  preferred) requirements should be among its first two bullets. A bullet further
  down that proves more than one of the first two gets this advice, at most one
  bullet for each of the first two that it would replace.
- move_project_up: a project in a projects section that proves required items no
  role shows should be read sooner.
- skills_first: when the skills section sits below experience and the job names
  many tools, some readers scan skills first. A suggestion only.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.models import (
    AdviceKind,
    EvidenceStrength,
    MatchStatus,
    Priority,
    Profile,
    RequirementMatch,
    ResumeDocument,
    Role,
    Section,
    SectionAdvice,
    Span,
    SpanKind,
)
from app.services.questions import supported_requirements
from app.services.skills import SkillCatalog
from app.services.text import section_for_heading

TOP_POSITIONS = 2
# How many distinct tools a job has to name before skills_first applies.
MANY_TOOLS = 8
_MAX_QUOTE_CHARS = 120
_MAX_LISTED = 3


def _quote(text: str) -> str:
    if len(text) > _MAX_QUOTE_CHARS:
        text = text[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return f'"{text}"'


def _ended(text: str) -> str:
    """Text that ends a sentence: a full stop after it, unless it already ends with one
    or with a quote that does."""
    if text.endswith((".", "!", "?")) or text[-2:] in ('."', '!"', '?"'):
        return text
    return f"{text}."


def _list(matches: Sequence[RequirementMatch]) -> str:
    quoted = [_quote(m.requirement.text) for m in matches[:_MAX_LISTED]]
    more = len(matches) - len(quoted)
    if more:
        quoted.append(f"{more} more")
    if len(quoted) <= 1:
        return "".join(quoted)
    return f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _proves(matches: Sequence[RequirementMatch]) -> str:
    required = [m for m in matches if m.requirement.priority is Priority.REQUIRED]
    preferred = [m for m in matches if m.requirement.priority is Priority.PREFERRED]
    parts = []
    if required:
        noun = "requirement" if len(required) == 1 else "requirements"
        parts.append(f"{len(required)} required {noun} ({_list(required)})")
    if preferred:
        noun = "item" if len(preferred) == 1 else "items"
        parts.append(f"{len(preferred)} preferred {noun} ({_list(preferred)})")
    return " and ".join(parts)


def _role_name(role: Role, header: str) -> str:
    if role.title and role.employer:
        return f"{role.title} at {role.employer}"
    return role.title or role.employer or _quote(header)


def _score(matches: Sequence[RequirementMatch]) -> tuple[int, int]:
    return (
        sum(m.requirement.priority is Priority.REQUIRED for m in matches),
        sum(m.requirement.priority is Priority.PREFERRED for m in matches),
    )


def _ranked(matches: Sequence[RequirementMatch]) -> list[RequirementMatch]:
    """Required, then preferred; job duties don't count for order."""
    return [m for m in matches if m.requirement.priority is not Priority.CONTEXT]


def bullet_advice(
    resume: ResumeDocument, profile: Profile, support: dict[str, list[RequirementMatch]]
) -> list[SectionAdvice]:
    spans = {span.id: span for span in resume.spans}
    advice: list[SectionAdvice] = []
    for role in profile.roles:
        bullets = [
            spans[i]
            for i in role.bullet_span_ids
            if i in spans and spans[i].kind is SpanKind.BULLET
        ]
        if len(bullets) <= TOP_POSITIONS:
            continue
        scores = [_score(_ranked(support.get(b.id, []))) for b in bullets]
        # Each lower bullet that proves more takes the place of the weakest of the
        # first two bullets that it beats, so the advice never pushes out a bullet
        # that proves as much.
        top = sorted(scores[:TOP_POSITIONS])
        lower = sorted(
            (
                (score, position)
                for position, score in enumerate(scores)
                if position >= TOP_POSITIONS and score > (0, 0)
            ),
            key=lambda item: (-item[0][0], -item[0][1], item[1]),
        )
        moves: list[int] = []
        for score, position in lower:
            if top and score > top[0]:
                moves.append(position)
                top.pop(0)
        header = spans[role.header_span_id].text if role.header_span_id in spans else ""
        for position in moves:
            bullet = bullets[position]
            proven = _ranked(support[bullet.id])
            advice.append(
                SectionAdvice(
                    kind=AdviceKind.MOVE_BULLET_UP,
                    message=(
                        f"Move this bullet up to the first two bullets of "
                        f"{_role_name(role, header)}: {_ended(_quote(bullet.text))} It is "
                        f"bullet {position + 1} of {len(bullets)} there and proves "
                        f"{_proves(proven)}, more than one of the first two bullets does."
                    ),
                    span_ids=[bullet.id],
                    requirement_ids=[m.requirement.id for m in proven],
                )
            )
    return advice


@dataclass
class _Project:
    header: Span
    spans: list[Span] = field(default_factory=list)


def _projects(resume: ResumeDocument) -> list[_Project]:
    """Projects in the projects sections: a line that isn't a bullet starts one, and
    the bullets after it belong to it."""
    projects: list[_Project] = []
    for span in resume.spans:
        if span.section is not Section.PROJECTS or span.kind is SpanKind.HEADING:
            continue
        if span.kind is not SpanKind.BULLET or not projects:
            projects.append(_Project(header=span))
        projects[-1].spans.append(span)
    return projects


def project_advice(
    resume: ResumeDocument, matches: Sequence[RequirementMatch], role_spans: set[str]
) -> list[SectionAdvice]:
    """A project that is the only work showing a skill a required requirement asks
    for, and that is read after the experience section or after another project."""
    projects = _projects(resume)
    if not projects:
        return []
    experience = [s.order for s in resume.spans if s.section is Section.EXPERIENCE]
    required = [
        m
        for m in matches
        if m.requirement.priority is Priority.REQUIRED
        and m.status in (MatchStatus.DIRECT, MatchStatus.PARTIAL)
    ]
    advice: list[SectionAdvice] = []
    for index, project in enumerate(projects):
        ids = {s.id for s in project.spans}
        skills: list[str] = []
        asking: list[RequirementMatch] = []
        for match in required:
            for skill in match.skills:
                shown = {
                    e.span_id for e in skill.evidence if e.strength is EvidenceStrength.DEMONSTRATED
                }
                if shown & ids and not shown & role_spans:
                    skills += [skill.skill] if skill.skill not in skills else []
                    asking += [match] if match not in asking else []
        after_experience = bool(experience) and project.header.order > min(experience)
        if not skills or not (after_experience or index > 0):
            continue
        where = (
            "Bring this project higher in the experience section, or move the projects "
            "section above experience"
            if after_experience
            else "Bring this project higher, to the top of the projects section"
        )
        noun = "requirement asks" if len(asking) == 1 else "requirements ask"
        advice.append(
            SectionAdvice(
                kind=AdviceKind.MOVE_PROJECT_UP,
                message=(
                    f"{where}: {_ended(_quote(project.header.text))} No role in your "
                    f"experience shows {_join(skills)}, which {len(asking)} required {noun} "
                    f"for: {_ended(_list(asking))}"
                ),
                span_ids=[s.id for s in project.spans],
                requirement_ids=[m.requirement.id for m in asking],
            )
        )
    return advice


def skills_advice(
    resume: ResumeDocument, matches: Sequence[RequirementMatch], catalog: SkillCatalog
) -> list[SectionAdvice]:
    def first(section: Section) -> Span | None:
        return next((s for s in resume.spans if s.section is section), None)

    skills, experience = first(Section.SKILLS), first(Section.EXPERIENCE)
    if skills is None or experience is None or skills.order < experience.order:
        return []
    asking = [m for m in matches if m.requirement.priority is not Priority.CONTEXT]
    tools: list[str] = []
    for match in asking:
        for skill in match.requirement.skills:
            if catalog.categories.get(skill) != "domain" and skill not in tools:
                tools.append(skill)
    if len(tools) < MANY_TOOLS:
        return []
    heading = next(
        (
            s
            for s in resume.spans
            if s.section is Section.SKILLS
            and s.kind is SpanKind.HEADING
            and section_for_heading(s.text) is Section.SKILLS
        ),
        skills,
    )
    named = ", ".join(tools[:4])
    return [
        SectionAdvice(
            kind=AdviceKind.SKILLS_FIRST,
            message=(
                f"A suggestion only: this job names {len(tools)} tools ({named} and more), "
                "and your skills section comes after your experience. Some readers scan the "
                "skills section first, so you could move it above experience. Either order "
                "is fine for this app."
            ),
            span_ids=[heading.id],
            requirement_ids=[m.requirement.id for m in asking if m.requirement.skills],
        )
    ]


def section_advice(
    resume: ResumeDocument,
    profile: Profile,
    matches: Sequence[RequirementMatch],
    catalog: SkillCatalog,
    role_spans: set[str],
) -> list[SectionAdvice]:
    """All advice, in the order: bullets within roles, projects, then sections."""
    support = supported_requirements(matches)
    return [
        *bullet_advice(resume, profile, support),
        *project_advice(resume, matches, role_spans),
        *skills_advice(resume, matches, catalog),
    ]
