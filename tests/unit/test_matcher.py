from app.models import (
    EvidenceStrength,
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
from tests.builders import build_pdf


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.PDF,
        page_count=1,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, page=1, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


RESUME = _resume(
    ("EXPERIENCE", Section.EXPERIENCE, SpanKind.HEADING),
    ("Built Airflow DAGs in Python", Section.EXPERIENCE, SpanKind.BULLET),
    ("SKILLS", Section.SKILLS, SpanKind.HEADING),
    ("Python, Kubernetes, Docker", Section.SKILLS, SpanKind.LINE),
)


def _match(catalog: SkillCatalog, skills: list[str], mode: MatchMode = MatchMode.ALL):  # type: ignore[no-untyped-def]
    req = Requirement(id="r0", text="x", priority=Priority.REQUIRED, skills=skills, match_mode=mode)
    return match_requirement(req, index_evidence(RESUME, skills, catalog))


def test_direct_when_shown_in_experience(catalog: SkillCatalog) -> None:
    result = _match(catalog, ["Python", "Airflow"])
    assert result.status is MatchStatus.DIRECT
    python = result.skills[0]
    # Experience evidence is listed before skills-section evidence.
    assert python.evidence[0].strength is EvidenceStrength.DEMONSTRATED
    assert python.evidence[0].span_id == "s1"
    assert python.evidence[1].section is Section.SKILLS


def test_partial_when_only_listed(catalog: SkillCatalog) -> None:
    result = _match(catalog, ["Kubernetes"])
    assert result.status is MatchStatus.PARTIAL
    assert result.skills[0].strength is EvidenceStrength.LISTED
    assert "only in your skills" in result.next_action


def test_partial_when_some_missing(catalog: SkillCatalog) -> None:
    result = _match(catalog, ["Python", "Kafka"])
    assert result.status is MatchStatus.PARTIAL
    assert "No evidence for Kafka" in result.next_action


def test_gap_when_nothing_found(catalog: SkillCatalog) -> None:
    result = _match(catalog, ["Kafka", "dbt"])
    assert result.status is MatchStatus.GAP
    assert all(m.evidence == [] for m in result.skills)


def test_any_of_needs_one(catalog: SkillCatalog) -> None:
    assert _match(catalog, ["Snowflake", "Airflow"], MatchMode.ANY).status is MatchStatus.DIRECT
    assert _match(catalog, ["Snowflake", "Docker"], MatchMode.ANY).status is MatchStatus.PARTIAL
    assert _match(catalog, ["Snowflake", "dbt"], MatchMode.ANY).status is MatchStatus.GAP


def test_not_assessed_without_skills(catalog: SkillCatalog) -> None:
    result = _match(catalog, [])
    assert result.status is MatchStatus.NOT_ASSESSED


def test_headings_are_never_evidence(catalog: SkillCatalog) -> None:
    resume = _resume(("Python", Section.OTHER, SpanKind.HEADING))
    assert index_evidence(resume, ["Python"], catalog)["Python"] == []


def test_without_headings_bullets_count_as_work(catalog: SkillCatalog) -> None:
    resume = _resume(
        ("Jordan Example", Section.HEADER, SpanKind.LINE),
        ("Built ETL jobs in Python", Section.HEADER, SpanKind.BULLET),
        ("Skills: Docker", Section.HEADER, SpanKind.LINE),
    )
    job = parse_job_description("Requirements\n- Python\n- Docker\n", catalog)
    report = build_report(resume, job, catalog)
    statuses = {m.requirement.text: m.status for m in report.matches}
    assert statuses == {"Python": MatchStatus.DIRECT, "Docker": MatchStatus.PARTIAL}
    assert any("No section headings" in w for w in report.warnings)


def test_report_end_to_end(
    catalog: SkillCatalog, data_engineer_markup: str, data_engineer_jd: str
) -> None:
    _, report = analyze(build_pdf(data_engineer_markup), data_engineer_jd)
    required = report.coverage[Priority.REQUIRED]
    assert (required.total, required.direct, required.partial) == (6, 4, 1)
    assert required.gap == 0
    assert report.missing_required_skills == []
    assert report.listed_but_not_demonstrated == ["Git", "CI/CD", "Kubernetes"]
    statuses = {m.requirement.text: m.status for m in report.matches}
    assert statuses["Experience with dbt"] is MatchStatus.GAP
    assert statuses["Comfortable with Git and CI/CD practices"] is MatchStatus.PARTIAL
    # Every evidence item points at a real span with its page.
    for match in report.matches:
        for skill in match.skills:
            for evidence in skill.evidence:
                assert evidence.page == 1
                assert evidence.matched_term.lower() in evidence.text.lower()


def test_wrong_resume_for_the_job(
    catalog: SkillCatalog, dotnet_markup: str, data_engineer_jd: str
) -> None:
    _, report = analyze(build_pdf(dotnet_markup), data_engineer_jd)
    assert report.coverage[Priority.REQUIRED].direct == 0
    assert "Python" in report.missing_required_skills
    assert "Databricks" in report.missing_required_skills
