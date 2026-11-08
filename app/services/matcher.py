"""Link each job requirement to resume evidence, or mark it as a gap.

Exact rules:
- Evidence is a resume span that names the skill.
- Evidence in experience, projects or certifications is "demonstrated".
  Evidence only in skills, summary or the header is "listed".
- A requirement is DIRECT when its skills are demonstrated, PARTIAL when some are
  missing or only listed, GAP when none appear, and NOT_ASSESSED when it names no
  skill the catalog knows.

Years:
- "5+ years of experience" with no skill is DIRECT when the dated roles add up to
  at least that many years, GAP when they don't, and NOT_ASSESSED when no role
  dates could be read.
- "7+ years with Java" keeps the skill rules above, but is at most PARTIAL when
  the roles that mention Java add up to fewer years.

Matching by meaning (optional) adds related evidence to every requirement. It never
changes a requirement that has exact evidence. A requirement that would be GAP or
NOT_ASSESSED becomes ADJACENT when a related line is found in experience or
projects; the person has to confirm it.
"""

import logging
from collections.abc import Collection, Iterable, Sequence
from datetime import date

from app import pipeline_version
from app.models import (
    AnalysisReport,
    CategoryCoverage,
    Evidence,
    EvidenceStrength,
    JobDescription,
    MatchingMode,
    MatchMode,
    MatchStatus,
    Priority,
    Profile,
    RelatedEvidence,
    Requirement,
    RequirementMatch,
    ResumeDocument,
    Section,
    SkillMatch,
    Span,
    SpanKind,
)
from app.services.semantic import SemanticMatcher
from app.services.skills import SkillCatalog, phrase_pattern
from app.services.structure import parse_profile, years_with_spans

logger = logging.getLogger("app.matcher")

DEMONSTRATED_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS, Section.CERTIFICATIONS}
# Related evidence has to come from real work to make a requirement ADJACENT.
ADJACENT_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS}
MAX_EVIDENCE_PER_SKILL = 5
_MAX_QUOTE_CHARS = 160

SEMANTIC_OFF_WARNING = (
    "Matching by meaning is off for this analysis, so only skills named exactly were "
    "matched. Related experience described in other words isn't shown."
)
SEMANTIC_FAILED_WARNING = (
    "Matching by meaning failed for this analysis, so only skills named exactly were matched."
)


def _join(names: list[str], word: str = "and") -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {word} {names[-1]}"


def _years_text(years: float) -> str:
    return "about 1 year" if years == 1 else f"about {years:g} years"


def _quote(text: str) -> str:
    if len(text) > _MAX_QUOTE_CHARS:
        text = text[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return f'"{text}"'


def _strength(span: Span, has_headings: bool) -> EvidenceStrength:
    if has_headings:
        in_work = span.section in DEMONSTRATED_SECTIONS
    else:
        # Without headings, bullets are the best available sign of real work.
        in_work = span.kind is SpanKind.BULLET
    return EvidenceStrength.DEMONSTRATED if in_work else EvidenceStrength.LISTED


def _has_headings(resume: ResumeDocument) -> bool:
    return any(span.kind is SpanKind.HEADING for span in resume.spans)


def index_evidence(
    resume: ResumeDocument, skills: Iterable[str], catalog: SkillCatalog
) -> dict[str, list[Evidence]]:
    """Evidence per skill. Catalog skills match through their catalog terms. A skill
    the catalog doesn't know (a free-text skill from the Claude parser) matches as a
    case-insensitive whole phrase."""
    wanted = set(skills)
    free_text = {skill: phrase_pattern(skill) for skill in wanted if not catalog.knows(skill)}
    has_headings = _has_headings(resume)
    index: dict[str, list[Evidence]] = {skill: [] for skill in wanted}

    def add(skill: str, span: Span, term: str) -> None:
        index[skill].append(
            Evidence(
                span_id=span.id,
                text=span.text,
                section=span.section,
                page=span.page,
                matched_term=term,
                strength=_strength(span, has_headings),
            )
        )

    for span in resume.spans:
        if span.kind is SpanKind.HEADING:
            continue
        for hit in catalog.find(span.text):
            if hit.skill in wanted:
                add(hit.skill, span, hit.term)
        for skill, pattern in free_text.items():
            found = pattern.search(span.text)
            if found is not None:
                add(skill, span, found.group())
    for evidence in index.values():
        # Demonstrated evidence first, then reading order (stable sort).
        evidence.sort(key=lambda e: e.strength is not EvidenceStrength.DEMONSTRATED)
    return index


def _skill_status(requirement: Requirement, skills: list[SkillMatch]) -> MatchStatus:
    found = [m for m in skills if m.strength is not None]
    shown = [m for m in found if m.strength is EvidenceStrength.DEMONSTRATED]
    if not skills:
        return MatchStatus.NOT_ASSESSED
    if requirement.match_mode is MatchMode.ANY:
        if shown:
            return MatchStatus.DIRECT
        return MatchStatus.PARTIAL if found else MatchStatus.GAP
    if len(shown) == len(skills):
        return MatchStatus.DIRECT
    return MatchStatus.PARTIAL if found else MatchStatus.GAP


def _skill_action(requirement: Requirement, status: MatchStatus, skills: list[SkillMatch]) -> str:
    if status is MatchStatus.DIRECT:
        return (
            "Supported by your work experience. Keep the strongest supporting bullet near "
            "the top of that role."
        )
    if status is MatchStatus.GAP:
        return (
            "Nothing in the resume supports this. Leave it out unless you have real "
            "experience with it. If you do, add a bullet that says where you used it."
        )

    listed = [m.skill for m in skills if m.strength is EvidenceStrength.LISTED]
    missing = [m.skill for m in skills if m.strength is None]
    parts: list[str] = []
    if listed:
        verb = "appears" if len(listed) == 1 else "appear"
        pronoun = "it" if len(listed) == 1 else "them"
        parts.append(
            f"{_join(listed)} {verb} only in your skills or summary. If you used {pronoun} "
            "in a job or project, add a bullet that says where and what you did."
        )
    if missing and requirement.match_mode is MatchMode.ALL:
        parts.append(f"No evidence for {_join(missing)}. Add only what you've actually used.")
    return " ".join(parts)


def _total_years_match(
    requirement: Requirement, profile: Profile | None
) -> tuple[MatchStatus, float | None, str]:
    """Status, years found and next action for "5+ years of experience"."""
    wanted = requirement.min_years
    total = profile.total_years if profile is not None else None
    if total is None:
        return (
            MatchStatus.NOT_ASSESSED,
            None,
            f"Asks for {wanted}+ years. No dates could be read from the roles in your "
            'resume, so check this one yourself. A date range such as "Mar 2022 - Present" '
            "on each role line lets the app count them.",
        )
    if wanted is not None and total >= wanted:
        return (
            MatchStatus.DIRECT,
            total,
            f"Asks for {wanted}+ years. The resume shows {_years_text(total)} across all "
            "roles. Check that enough of that time is the kind of work this asks for.",
        )
    return (
        MatchStatus.GAP,
        total,
        f"Asks for {wanted}+ years. The resume shows {_years_text(total)}. Don't stretch "
        "dates to close the gap. If you have earlier relevant work that isn't listed, add "
        "it with its real dates.",
    )


def _skill_years(
    requirement: Requirement,
    index: dict[str, list[Evidence]],
    profile: Profile | None,
) -> tuple[float | None, str | None]:
    """Years shown with the requirement's skills and the skill that decides it.

    ALL requirements are limited by the skill with the fewest years, ANY
    requirements by the skill with the most. None when no role dates exist.
    """
    if profile is None:
        return None, None
    per_skill: dict[str, float] = {}
    for skill in requirement.skills:
        span_ids = {e.span_id for e in index.get(skill, [])}
        years = years_with_spans(profile, span_ids)
        if years is None:
            return None, None
        per_skill[skill] = years
    pick = max if requirement.match_mode is MatchMode.ANY else min
    skill = pick(per_skill, key=lambda name: per_skill[name])
    return per_skill[skill], skill


def _adjacent_action(
    requirement: Requirement, skills: list[SkillMatch], best: RelatedEvidence
) -> str:
    missing = [m.skill for m in skills if m.strength is None]
    if missing:
        word = "or" if requirement.match_mode is MatchMode.ANY else "and"
        opening = f"The resume doesn't name {_join(missing, word)}, but this line looks related:"
    else:
        opening = "No exact match, but this line looks related:"
    quote = _quote(best.text)
    # The quote already ends a sentence when the bullet ends with a period.
    end = " " if quote[-2] in ".!?" else ". "
    return (
        f"{opening} {quote}{end}Check that it really shows this requirement. If it does, "
        "use the job description's wording in that bullet only where it is true."
    )


def match_requirement(
    requirement: Requirement,
    index: dict[str, list[Evidence]],
    *,
    profile: Profile | None = None,
    related: Sequence[RelatedEvidence] = (),
    work_span_ids: Collection[str] | None = None,
    semantic: bool = False,
) -> RequirementMatch:
    """Match one requirement.

    `related` is the output of matching by meaning for this requirement.
    `work_span_ids` lists the spans that count as real work for an ADJACENT result;
    when None, spans in experience and projects count.
    """
    skill_matches: list[SkillMatch] = []
    for skill in requirement.skills:
        evidence = index.get(skill, [])
        strength = evidence[0].strength if evidence else None
        skill_matches.append(
            SkillMatch(skill=skill, strength=strength, evidence=evidence[:MAX_EVIDENCE_PER_SKILL])
        )

    years_only = bool(requirement.min_years) and not requirement.skills
    years_found: float | None = None
    if years_only:
        status, years_found, action = _total_years_match(requirement, profile)
    else:
        status = _skill_status(requirement, skill_matches)
        action = _skill_action(requirement, status, skill_matches)
        if requirement.min_years and status in (MatchStatus.DIRECT, MatchStatus.PARTIAL):
            years_found, deciding_skill = _skill_years(requirement, index, profile)
            action = _with_years_note(requirement, status, action, years_found, deciding_skill)
            if years_found is None or years_found < requirement.min_years:
                status = MatchStatus.PARTIAL

    # Related lines that are already exact evidence add nothing.
    exact_ids = {e.span_id for skill in requirement.skills for e in index.get(skill, [])}
    related_evidence = [r for r in related if r.span_id not in exact_ids]

    if status in (MatchStatus.GAP, MatchStatus.NOT_ASSESSED) and not years_only:
        in_work = [
            r
            for r in related_evidence
            if (
                r.span_id in work_span_ids
                if work_span_ids is not None
                else r.section in ADJACENT_SECTIONS
            )
        ]
        if in_work:
            best = max(in_work, key=lambda r: r.score)
            status = MatchStatus.ADJACENT
            action = _adjacent_action(requirement, skill_matches, best)
        elif status is MatchStatus.NOT_ASSESSED:
            action = (
                "Names no specific skill, and no closely related line was found by meaning. "
                "Check it yourself."
                if semantic
                else "Names no specific skill, so keyword matching can't assess it. "
                "Check it yourself."
            )

    return RequirementMatch(
        requirement=requirement,
        status=status,
        skills=skill_matches,
        related_evidence=related_evidence,
        years_found=years_found,
        next_action=action,
    )


def _with_years_note(
    requirement: Requirement,
    status: MatchStatus,
    action: str,
    years: float | None,
    skill: str | None,
) -> str:
    """Add the years shown with the requirement's skills to the next action."""
    wanted = requirement.min_years or 0
    names = _join(requirement.skills, "or" if requirement.match_mode is MatchMode.ANY else "and")
    if years is None or skill is None:
        note = (
            f"Asks for {wanted}+ years with {names}. No dates could be read from your roles, "
            "so those years couldn't be counted and this is partial at most. A date range on "
            "each role line lets the app count them."
        )
        return note if status is MatchStatus.DIRECT else f"{note} {action}"
    if years >= wanted:
        return f"{action} Roles that mention {skill} add up to {_years_text(years)}."
    if years == 0:
        shown = f"None of your dated roles mention {skill}"
    else:
        shown = f"Roles that mention {skill} add up to {_years_text(years)}"
    note = f"Asks for {wanted}+ years with {names}. {shown}, so this is partial at most."
    if status is MatchStatus.DIRECT:
        # The skill is shown; only the years fall short.
        return (
            f"{note} Don't stretch dates. If earlier work with {skill} is missing from the "
            "resume, add it with its real dates."
        )
    return f"{note} {action}"


def _dedupe(names: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def _warnings(resume: ResumeDocument, job: JobDescription) -> list[str]:
    warnings: list[str] = []
    if not _has_headings(resume):
        warnings.append(
            "No section headings were recognized in the resume, so bullets are treated as "
            "work experience and everything else as listed skills."
        )
    elif Section.EXPERIENCE not in resume.sections_found:
        warnings.append("No experience section was found in the resume.")
    if not job.requirements:
        warnings.append("No requirements were found in the job description.")
    elif sum(1 for r in job.requirements if r.skills) < 3:
        warnings.append(
            "Few named skills were found in the job description, so most requirements "
            "need a manual check."
        )
    return warnings


def _work_span_ids(resume: ResumeDocument) -> set[str]:
    if _has_headings(resume):
        return {s.id for s in resume.spans if s.section in ADJACENT_SECTIONS}
    return {s.id for s in resume.spans if s.kind is SpanKind.BULLET}


def build_report(
    resume: ResumeDocument,
    job: JobDescription,
    catalog: SkillCatalog,
    *,
    semantic: SemanticMatcher | None = None,
    today: date | None = None,
) -> AnalysisReport:
    profile = parse_profile(resume, today)
    all_skills = {skill for r in job.requirements for skill in r.skills}
    index = index_evidence(resume, all_skills, catalog)
    warnings = _warnings(resume, job)

    related: dict[str, list[RelatedEvidence]] = {}
    semantic_ran = False
    if semantic is None:
        warnings.append(SEMANTIC_OFF_WARNING)
    else:
        try:
            related = semantic.find_related(resume, job.requirements)
            semantic_ran = True
        except Exception:
            # A model failure must not lose the exact results.
            logger.exception("matching by meaning failed")
            warnings.append(SEMANTIC_FAILED_WARNING)

    work_ids = _work_span_ids(resume)
    matches = [
        match_requirement(
            r,
            index,
            profile=profile,
            related=related.get(r.id, []),
            work_span_ids=work_ids,
            semantic=semantic_ran,
        )
        for r in job.requirements
    ]

    coverage = {priority: CategoryCoverage() for priority in Priority}
    for match in matches:
        bucket = coverage[match.requirement.priority]
        bucket.total += 1
        setattr(bucket, match.status.value, getattr(bucket, match.status.value) + 1)

    missing_required = _dedupe(
        sm.skill
        for m in matches
        if m.requirement.priority is Priority.REQUIRED
        and (
            m.requirement.match_mode is MatchMode.ALL
            or m.status in (MatchStatus.GAP, MatchStatus.ADJACENT)
        )
        for sm in m.skills
        if sm.strength is None
    )
    listed_only = _dedupe(
        sm.skill
        for m in matches
        if m.requirement.priority is not Priority.CONTEXT
        for sm in m.skills
        if sm.strength is EvidenceStrength.LISTED
    )

    return AnalysisReport(
        pipeline_version=pipeline_version(semantic_ran),
        matching_mode=MatchingMode.SEMANTIC if semantic_ran else MatchingMode.EXACT,
        job=job,
        resume_sections=resume.sections_found,
        warnings=warnings,
        coverage=coverage,
        missing_required_skills=missing_required,
        listed_but_not_demonstrated=listed_only,
        profile=profile,
        matches=matches,
    )
