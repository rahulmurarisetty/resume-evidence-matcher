import pytest

from app.models import MatchStatus, Section, SpanKind
from app.services.jd_parser import parse_job_description
from app.services.matcher import build_report
from app.services.skills import SkillCatalog
from app.services.text import section_for_heading
from app.services.versions import version_asks
from tests.unit.test_matcher import _resume


@pytest.mark.parametrize(
    ("text", "asks"),
    [
        ("Experience with Angular 12 or later", [("Angular", (12,))]),
        ("Java 11+ and Spring Boot", [("Java", (11,))]),
        ("Python 3.10 or newer", [("Python", (3, 10))]),
        ("5+ years of Java", []),
        ("Java 8 experience", []),
        ("React 18 and above", [("React", (18,))]),
    ],
)
def test_version_asks(
    catalog: SkillCatalog, text: str, asks: list[tuple[str, tuple[int, ...]]]
) -> None:
    assert [(a.skill, a.minimum) for a in version_asks(text, catalog)] == asks


def _status(catalog: SkillCatalog, requirement: str, bullet: str) -> tuple[MatchStatus, str]:
    resume = _resume(
        ("EXPERIENCE", Section.EXPERIENCE, SpanKind.HEADING),
        ("Developer, Example Corp | Jan 2020 - Present", Section.EXPERIENCE, SpanKind.LINE),
        (bullet, Section.EXPERIENCE, SpanKind.BULLET),
    )
    job = parse_job_description(f"Requirements\n- {requirement}\n", catalog)
    [match] = build_report(resume, job, catalog).matches
    return match.status, match.next_action


@pytest.mark.parametrize(
    ("bullet", "status"),
    [
        ("Built Angular 14 screens for policy servicing", MatchStatus.DIRECT),
        ("Upgraded Angular 9 to Angular 15", MatchStatus.DIRECT),
        ("Built Angular screens for policy servicing", MatchStatus.PARTIAL),
        ("Maintained Angular 10 screens", MatchStatus.PARTIAL),
    ],
)
def test_minimum_version_must_be_shown(
    catalog: SkillCatalog, bullet: str, status: MatchStatus
) -> None:
    found, action = _status(catalog, "Experience with Angular 12 or later", bullet)
    assert found is status
    if status is MatchStatus.PARTIAL:
        assert action.startswith("Asks for Angular 12 or later.")


def test_any_of_versions_needs_one(catalog: SkillCatalog) -> None:
    found, _ = _status(catalog, "Angular 12+ or React 18+", "Built React 18 pages")
    assert found is MatchStatus.DIRECT


def test_tools_is_a_skills_heading() -> None:
    assert section_for_heading("TOOLS") is Section.SKILLS
    assert section_for_heading("Tools & Technologies") is Section.SKILLS
    assert section_for_heading("Professional Background") is Section.EXPERIENCE
    assert section_for_heading("Licenses & Certifications") is Section.CERTIFICATIONS
