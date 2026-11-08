"""Link each job requirement to resume evidence, or mark it as a gap.

Rules for exact matching:
- Evidence is a resume span that names the skill.
- Evidence in experience, projects or certifications is "demonstrated".
  Evidence only in skills, summary or the header is "listed".
- A requirement is DIRECT when its skills are demonstrated, PARTIAL when some are
  missing or only listed, GAP when none appear, and NOT_ASSESSED when it names no
  skill the catalog knows.
"""

from collections.abc import Iterable

from app import PIPELINE_VERSION
from app.models import (
    AnalysisReport,
    CategoryCoverage,
    Evidence,
    EvidenceStrength,
    JobDescription,
    MatchMode,
    MatchStatus,
    Priority,
    Requirement,
    RequirementMatch,
    ResumeDocument,
    Section,
    SkillMatch,
    Span,
    SpanKind,
)
from app.services.skills import SkillCatalog

DEMONSTRATED_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS, Section.CERTIFICATIONS}
MAX_EVIDENCE_PER_SKILL = 5


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


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
    wanted = set(skills)
    has_headings = _has_headings(resume)
    index: dict[str, list[Evidence]] = {skill: [] for skill in wanted}
    for span in resume.spans:
        if span.kind is SpanKind.HEADING:
            continue
        for hit in catalog.find(span.text):
            if hit.skill not in wanted:
                continue
            index[hit.skill].append(
                Evidence(
                    span_id=span.id,
                    text=span.text,
                    section=span.section,
                    page=span.page,
                    matched_term=hit.term,
                    strength=_strength(span, has_headings),
                )
            )
    for evidence in index.values():
        # Demonstrated evidence first, then reading order (stable sort).
        evidence.sort(key=lambda e: e.strength is not EvidenceStrength.DEMONSTRATED)
    return index


def _next_action(requirement: Requirement, status: MatchStatus, skills: list[SkillMatch]) -> str:
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
    if status is MatchStatus.NOT_ASSESSED:
        if requirement.min_years:
            return (
                f"Asks for {requirement.min_years}+ years. Total years of experience aren't "
                "calculated yet, so check this one yourself."
            )
        return "Names no specific skill, so keyword matching can't assess it. Check it yourself."

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


def match_requirement(
    requirement: Requirement, index: dict[str, list[Evidence]]
) -> RequirementMatch:
    skill_matches: list[SkillMatch] = []
    for skill in requirement.skills:
        evidence = index.get(skill, [])
        strength = evidence[0].strength if evidence else None
        skill_matches.append(
            SkillMatch(skill=skill, strength=strength, evidence=evidence[:MAX_EVIDENCE_PER_SKILL])
        )

    found = [m for m in skill_matches if m.strength is not None]
    shown = [m for m in found if m.strength is EvidenceStrength.DEMONSTRATED]

    if not skill_matches:
        status = MatchStatus.NOT_ASSESSED
    elif requirement.match_mode is MatchMode.ANY:
        status = (
            MatchStatus.DIRECT if shown else (MatchStatus.PARTIAL if found else MatchStatus.GAP)
        )
    elif len(shown) == len(skill_matches):
        status = MatchStatus.DIRECT
    else:
        status = MatchStatus.PARTIAL if found else MatchStatus.GAP

    return RequirementMatch(
        requirement=requirement,
        status=status,
        skills=skill_matches,
        next_action=_next_action(requirement, status, skill_matches),
    )


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


def build_report(
    resume: ResumeDocument, job: JobDescription, catalog: SkillCatalog
) -> AnalysisReport:
    all_skills = {skill for r in job.requirements for skill in r.skills}
    index = index_evidence(resume, all_skills, catalog)
    matches = [match_requirement(r, index) for r in job.requirements]

    coverage = {priority: CategoryCoverage() for priority in Priority}
    for match in matches:
        bucket = coverage[match.requirement.priority]
        bucket.total += 1
        setattr(bucket, match.status.value, getattr(bucket, match.status.value) + 1)

    missing_required = _dedupe(
        sm.skill
        for m in matches
        if m.requirement.priority is Priority.REQUIRED
        and (m.requirement.match_mode is MatchMode.ALL or m.status is MatchStatus.GAP)
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
        pipeline_version=PIPELINE_VERSION,
        job=job,
        resume_sections=resume.sections_found,
        warnings=_warnings(resume, job),
        coverage=coverage,
        missing_required_skills=missing_required,
        listed_but_not_demonstrated=listed_only,
        matches=matches,
    )
