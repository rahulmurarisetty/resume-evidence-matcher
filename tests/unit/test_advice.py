"""Section order advice and metric questions, on small hand-made resumes."""

from datetime import date

from app.models import (
    AdviceKind,
    AnalysisReport,
    FileType,
    ResumeDocument,
    Section,
    Span,
    SpanKind,
)
from app.services.jd_parser import parse_job_description
from app.services.matcher import build_report
from app.services.questions import METRIC_ASK, all_questions, metric_questions
from app.services.skills import SkillCatalog

TODAY = date(2026, 11, 8)
H, B, L = SpanKind.HEADING, SpanKind.BULLET, SpanKind.LINE
E, P, S, X = Section.EXPERIENCE, Section.PROJECTS, Section.SKILLS, Section.HEADER


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.DOCX,
        page_count=None,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


def _report(resume: ResumeDocument, jd: str, catalog: SkillCatalog) -> AnalysisReport:
    return build_report(resume, parse_job_description(jd, catalog), catalog, today=TODAY)


JD = """Platform Engineer

Requirements
- Experience running Kubernetes in production
- Strong Terraform skills
- Experience with Rust

Nice to have
- Experience with Prometheus
"""


def _platform_resume() -> ResumeDocument:
    return _resume(
        ("Casey Sample", X, L),
        ("EXPERIENCE", E, H),
        ("Platform Engineer, Northwind Freight | Jan 2021 - Present", E, L),
        ("Ran the weekly on-call rotation for the platform team.", E, B),
        ("Wrote runbooks for 12 incident types.", E, B),
        ("Moved 40 services onto Kubernetes clusters built with Terraform.", E, B),
        ("Added Prometheus alerts for the Kubernetes control plane.", E, B),
        ("PROJECTS", P, H),
        ("Release notes bot", P, L),
        ("A Slack bot that drafts release notes.", P, B),
        ("Log shipper", P, L),
        ("A small log shipper written in Rust.", P, B),
        ("SKILLS", S, H),
        ("Kubernetes, Terraform, Rust, Prometheus", S, L),
    )


def test_bullets_that_prove_more_are_advised_up(catalog: SkillCatalog) -> None:
    report = _report(_platform_resume(), JD, catalog)
    moves = [a for a in report.section_advice if a.kind is AdviceKind.MOVE_BULLET_UP]
    assert [a.span_ids for a in moves] == [["s5"], ["s6"]]
    by_text = {m.requirement.id: m.requirement.text for m in report.matches}
    first = moves[0]
    assert [by_text[r] for r in first.requirement_ids] == [
        "Experience running Kubernetes in production",
        "Strong Terraform skills",
    ]
    assert first.message.startswith(
        "Move this bullet up to the first two bullets of Platform Engineer at Northwind "
        'Freight: "Moved 40 services onto Kubernetes clusters built with Terraform." It is '
        "bullet 3 of 4 there and proves 2 required requirements"
    )
    # The second one proves one required and one preferred item.
    assert "1 required requirement" in moves[1].message
    assert "1 preferred item" in moves[1].message


def test_no_bullet_advice_when_the_best_bullets_are_already_first(
    catalog: SkillCatalog,
) -> None:
    resume = _resume(
        ("EXPERIENCE", E, H),
        ("Platform Engineer, Northwind Freight | Jan 2021 - Present", E, L),
        ("Moved 40 services onto Kubernetes clusters built with Terraform.", E, B),
        ("Added Prometheus alerts for the Kubernetes control plane.", E, B),
        ("Ran the weekly on-call rotation for the platform team.", E, B),
    )
    report = _report(resume, JD, catalog)
    assert not [a for a in report.section_advice if a.kind is AdviceKind.MOVE_BULLET_UP]


def test_bullet_advice_never_pushes_out_a_bullet_that_proves_as_much(
    catalog: SkillCatalog,
) -> None:
    resume = _resume(
        ("EXPERIENCE", E, H),
        ("Platform Engineer, Northwind Freight | Jan 2021 - Present", E, L),
        ("Moved 40 services onto Kubernetes clusters built with Terraform.", E, B),
        ("Ran the weekly on-call rotation for the platform team.", E, B),
        ("Wrote Terraform modules for the shared network.", E, B),
        ("Wrote Rust tools for the release train.", E, B),
    )
    report = _report(resume, JD, catalog)
    moves = [a for a in report.section_advice if a.kind is AdviceKind.MOVE_BULLET_UP]
    # Only the on-call bullet proves nothing, so only one bullet is advised up: the
    # first of the two that tie, in reading order.
    assert [a.span_ids for a in moves] == [["s4"]]


def test_a_project_that_alone_shows_a_required_skill(catalog: SkillCatalog) -> None:
    report = _report(_platform_resume(), JD, catalog)
    [project] = [a for a in report.section_advice if a.kind is AdviceKind.MOVE_PROJECT_UP]
    assert project.span_ids == ["s10", "s11"]
    assert [
        m.requirement.text for m in report.matches if m.requirement.id in (project.requirement_ids)
    ] == ["Experience with Rust"]
    assert project.message == (
        "Bring this project higher in the experience section, or move the projects section "
        'above experience: "Log shipper". No role in your experience shows Rust, which 1 '
        'required requirement asks for: "Experience with Rust".'
    )


def test_skills_first_is_a_suggestion_for_jobs_with_many_tools(catalog: SkillCatalog) -> None:
    many = """Backend Engineer

Requirements
- Python, Django, PostgreSQL, Redis and Celery
- Docker, Kubernetes and Terraform on AWS
"""
    report = _report(_platform_resume(), many, catalog)
    [advice] = [a for a in report.section_advice if a.kind is AdviceKind.SKILLS_FIRST]
    # "Terraform" also counts as infrastructure as code: 10 tools in all.
    assert advice.message.startswith("A suggestion only: this job names 10 tools")
    assert advice.span_ids == ["s12"]  # the skills heading
    # Few tools: no advice. Skills above experience: no advice.
    assert not [
        a
        for a in _report(_platform_resume(), JD, catalog).section_advice
        if a.kind is AdviceKind.SKILLS_FIRST
    ]
    skills_on_top = _resume(
        ("SKILLS", S, H),
        ("Python, Django", S, L),
        ("EXPERIENCE", E, H),
        ("Backend Engineer, Example Corp | Jan 2021 - Present", E, L),
        ("Built Django services.", E, B),
    )
    assert not _report(skills_on_top, many, catalog).section_advice


def test_advice_never_changes_the_resume(catalog: SkillCatalog) -> None:
    resume = _platform_resume()
    before = resume.model_dump()
    report = _report(resume, JD, catalog)
    assert report.section_advice
    assert resume.model_dump() == before


# ---------------------------------------------------------------------------
# Metric questions
# ---------------------------------------------------------------------------


def test_metric_questions_ask_about_bullets_without_a_number(catalog: SkillCatalog) -> None:
    resume = _platform_resume()
    report = _report(resume, JD, catalog)
    questions = metric_questions(report, resume)
    # The two bullets with numbers ("12", "40") get none, and the project bullets
    # aren't experience. The Kubernetes and Prometheus bullet supports a required
    # requirement, so it comes before the on-call bullet, which supports nothing.
    assert [q.span_id for q in questions] == ["s6", "s3"]
    first = questions[0]
    assert first.kind == "metric" and first.id == "metric-s6"
    assert first.requirement_text == "Experience running Kubernetes in production"
    assert first.question == (
        'No number in this bullet: "Added Prometheus alerts for the Kubernetes control '
        f'plane." {METRIC_ASK}'
    )
    assert METRIC_ASK == (
        "How many, how much, how fast or how often? Add a number only if you know it."
    )
    assert questions[1].requirement_id is None


def test_at_most_five_metric_questions_required_first(catalog: SkillCatalog) -> None:
    bullets = [(f"Maintained internal tool number {name}.", E, B) for name in "ABCDEF"]
    resume = _resume(
        ("EXPERIENCE", E, H),
        ("Platform Engineer, Northwind Freight | Jan 2021 - Present", E, L),
        *bullets,
        ("Wrote Rust services for the billing team.", E, B),
        ("Mentored three new engineers.", E, B),  # a number written as a word
    )
    report = _report(resume, JD, catalog)
    questions = metric_questions(report, resume)
    assert len(questions) == 5
    assert questions[0].line == "Wrote Rust services for the billing team."
    assert all("three" not in (q.line or "") for q in questions)
    # Gap questions come first in the combined list; no lines, no metric questions.
    combined = all_questions(report, resume, catalog)
    kinds = [q.kind for q in combined]
    assert kinds == sorted(kinds)  # "gap" before "metric"
    assert all(q.kind == "gap" for q in all_questions(report, None, catalog))


def test_advice_names_the_client_when_two_roles_share_a_title(catalog: SkillCatalog) -> None:
    # Consultant resumes repeat a title and name a client instead of an employer.
    resume = _resume(
        ("EXPERIENCE", E, H),
        ("Platform Engineer Jan 2023 - Present", E, L),
        ("Client: Northwind Freight | Remote, USA", E, L),
        ("Ran the weekly on-call rotation for the platform team.", E, B),
        ("Wrote runbooks for 12 incident types.", E, B),
        ("Moved 40 services onto Kubernetes clusters built with Terraform.", E, B),
        ("Platform Engineer Jan 2020 - Dec 2022", E, L),
        ("Client: Contoso Shipping | Remote, USA", E, L),
        ("Kept the build farm patched.", E, B),
        ("Answered support tickets for the build farm.", E, B),
        ("Wrote Rust tools for log shipping.", E, B),
    )
    report = _report(resume, JD, catalog)
    moves = [a.message for a in report.section_advice if a.kind is AdviceKind.MOVE_BULLET_UP]
    assert any("Platform Engineer (client: Northwind Freight)" in m for m in moves)
    assert any("Platform Engineer (client: Contoso Shipping)" in m for m in moves)
