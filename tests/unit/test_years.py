from datetime import date

from app.models import (
    FileType,
    MatchMode,
    MatchStatus,
    Priority,
    Requirement,
    ResumeDocument,
    Section,
    Span,
    SpanKind,
)
from app.services.analysis import analyze
from app.services.jd_parser import parse_job_description
from app.services.matcher import build_report, index_evidence, match_requirement
from app.services.skills import SkillCatalog
from app.services.structure import parse_profile
from tests.builders import build_pdf

TODAY = date(2026, 11, 8)
E, S = Section.EXPERIENCE, Section.SKILLS
H, B, L = SpanKind.HEADING, SpanKind.BULLET, SpanKind.LINE


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.PDF,
        page_count=1,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, page=1, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


# Java appears in a 2-year role only; Python in both roles (6 years in total).
RESUME = _resume(
    ("EXPERIENCE", E, H),
    ("Backend Developer, Example Corp | Jan 2021 - Dec 2022", E, L),
    ("Built Java services and Python tooling", E, B),
    ("Data Engineer, Sample Group | Jan 2017 - Dec 2020", E, L),
    ("Wrote Python ETL jobs", E, B),
    ("SKILLS", S, H),
    ("Python, Java, Go, Kubernetes", S, L),
)
UNDATED = _resume(
    ("EXPERIENCE", E, H),
    ("Backend Developer, Example Corp", E, L),
    ("Built Java services", E, B),
)


def _match(
    catalog: SkillCatalog,
    text: str,
    skills: list[str],
    years: int,
    resume: ResumeDocument = RESUME,
    mode: MatchMode = MatchMode.ALL,
):  # type: ignore[no-untyped-def]
    requirement = Requirement(
        id="r0",
        text=text,
        priority=Priority.REQUIRED,
        skills=skills,
        match_mode=mode,
        min_years=years,
    )
    profile = parse_profile(resume, today=TODAY)
    return match_requirement(requirement, index_evidence(resume, skills, catalog), profile=profile)


def test_total_years_met(catalog: SkillCatalog) -> None:
    result = _match(catalog, "5+ years of experience", [], 5)
    assert result.status is MatchStatus.DIRECT
    assert result.years_found == 6.0
    assert "The resume shows about 6 years across all roles" in result.next_action


def test_total_years_not_met(catalog: SkillCatalog) -> None:
    result = _match(catalog, "8+ years of experience", [], 8)
    assert result.status is MatchStatus.GAP
    assert result.years_found == 6.0
    assert "The resume shows about 6 years" in result.next_action
    assert "Don't stretch dates" in result.next_action


def test_total_years_without_dates(catalog: SkillCatalog) -> None:
    result = _match(catalog, "5+ years of experience", [], 5, resume=UNDATED)
    assert result.status is MatchStatus.NOT_ASSESSED
    assert result.years_found is None
    assert "No dates could be read" in result.next_action


def test_total_years_without_profile(catalog: SkillCatalog) -> None:
    requirement = Requirement(
        id="r0", text="3+ years", priority=Priority.REQUIRED, skills=[], min_years=3
    )
    result = match_requirement(requirement, {})
    assert result.status is MatchStatus.NOT_ASSESSED


def test_skill_years_limit_status_to_partial(catalog: SkillCatalog) -> None:
    result = _match(catalog, "5+ yrs with Java", ["Java"], 5)
    assert result.status is MatchStatus.PARTIAL
    assert result.years_found == 2.0
    assert "Roles that mention Java add up to about 2 years" in result.next_action
    assert "partial at most" in result.next_action


def test_skill_years_met_keeps_direct(catalog: SkillCatalog) -> None:
    result = _match(catalog, "5+ years with Python", ["Python"], 5)
    assert result.status is MatchStatus.DIRECT
    assert result.years_found == 6.0
    assert "Roles that mention Python add up to about 6 years" in result.next_action


def test_all_of_is_limited_by_the_shortest_skill(catalog: SkillCatalog) -> None:
    result = _match(catalog, "3+ years with Python and Java", ["Python", "Java"], 3)
    assert result.status is MatchStatus.PARTIAL
    assert result.years_found == 2.0
    assert "mention Java" in result.next_action


def test_any_of_uses_the_longest_skill(catalog: SkillCatalog) -> None:
    result = _match(
        catalog, "3+ years with Java or Python", ["Java", "Python"], 3, mode=MatchMode.ANY
    )
    assert result.status is MatchStatus.DIRECT
    assert result.years_found == 6.0


def test_listed_only_skill_with_years(catalog: SkillCatalog) -> None:
    result = _match(catalog, "2+ years with Kubernetes", ["Kubernetes"], 2)
    assert result.status is MatchStatus.PARTIAL
    assert result.years_found == 0.0
    assert "None of your dated roles mention Kubernetes" in result.next_action
    assert "only in your skills" in result.next_action


def test_missing_skill_with_years_stays_gap(catalog: SkillCatalog) -> None:
    result = _match(catalog, "3+ years with Kafka", ["Kafka"], 3)
    assert result.status is MatchStatus.GAP
    assert result.years_found is None


def test_skill_years_without_dates_is_partial_at_most(catalog: SkillCatalog) -> None:
    result = _match(catalog, "1+ years with Java", ["Java"], 1, resume=UNDATED)
    assert result.status is MatchStatus.PARTIAL
    assert result.years_found is None
    assert "No dates could be read" in result.next_action


def test_parsed_job_description(catalog: SkillCatalog) -> None:
    job = parse_job_description(
        "Requirements\n- 5+ years of experience\n- 7+ yrs with Java\n- 10+ years of experience\n",
        catalog,
    )
    report = build_report(RESUME, job, catalog, today=TODAY)
    statuses = [m.status for m in report.matches]
    assert statuses == [MatchStatus.DIRECT, MatchStatus.PARTIAL, MatchStatus.GAP]
    assert report.profile.total_years == 6.0


def test_sample_report_includes_profile(data_engineer_markup: str, data_engineer_jd: str) -> None:
    _, report = analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=TODAY)
    years = next(m for m in report.matches if m.requirement.min_years == 5)
    assert years.status is MatchStatus.DIRECT
    assert years.years_found == 7.5
    assert report.profile.total_years == 7.5
    assert len(report.profile.roles) == 2
