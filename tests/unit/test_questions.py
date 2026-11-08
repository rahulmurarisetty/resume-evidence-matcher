from datetime import date

from app.models import (
    EvidenceStrength,
    MatchMode,
    MatchStatus,
    Priority,
    RelatedEvidence,
    Requirement,
    RequirementMatch,
    Section,
    SkillMatch,
)
from app.services.analysis import analyze
from app.services.questions import gap_questions, question_for
from tests.builders import build_pdf
from tests.fakes import FakeEncoder, FakeReranker


def _match(
    status: MatchStatus,
    skills: list[str],
    *,
    mode: MatchMode = MatchMode.ALL,
    min_years: int | None = None,
    found: tuple[str, ...] = (),
    related: list[RelatedEvidence] | None = None,
) -> RequirementMatch:
    return RequirementMatch(
        requirement=Requirement(
            id="r0",
            text="Experience with the listed tools",
            priority=Priority.REQUIRED,
            skills=skills,
            match_mode=mode,
            min_years=min_years,
        ),
        status=status,
        skills=[
            SkillMatch(
                skill=s,
                strength=EvidenceStrength.DEMONSTRATED if s in found else None,
                evidence=[],
            )
            for s in skills
        ],
        related_evidence=related or [],
        next_action="",
    )


def test_sample_gap_questions(data_engineer_markup: str, data_engineer_jd: str) -> None:
    _, report = analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=date(2026, 11, 8))
    questions = {q.requirement_text: q for q in gap_questions(report)}
    assert set(questions) == {"Experience with dbt", "Kafka or other streaming tools"}
    assert questions["Experience with dbt"].question == (
        "Have you used dbt? If yes, where, and what did you build with it?"
    )
    assert questions["Experience with dbt"].status is MatchStatus.GAP
    assert questions["Kafka or other streaming tools"].priority is Priority.PREFERRED
    # The same report always gets the same questions.
    assert gap_questions(report) == gap_questions(report)


def test_several_skills_and_alternatives() -> None:
    both = _match(MatchStatus.GAP, ["Kafka", "Flink"])
    assert question_for(both) == (
        "Have you used Kafka and Flink? If yes, where, and what did you build with them?"
    )
    either = _match(MatchStatus.GAP, ["Kafka", "Flink"], mode=MatchMode.ANY)
    assert question_for(either) == (
        "Have you used Kafka or Flink? If yes, where, and what did you build with it?"
    )
    partly = _match(MatchStatus.GAP, ["Python", "Kafka"], found=("Python",))
    assert question_for(partly) == (
        "Have you used Kafka? If yes, where, and what did you build with it?"
    )


def test_domains_are_asked_about_as_work() -> None:
    assert question_for(_match(MatchStatus.GAP, ["Insurance"])) == (
        "Have you worked in Insurance? If yes, where, and what did you work on?"
    )


def test_years_only_gap() -> None:
    question = question_for(_match(MatchStatus.GAP, [], min_years=5))
    assert question is not None
    assert question.startswith("The job asks for 5+ years.")


def test_gap_without_a_missing_skill() -> None:
    question = question_for(_match(MatchStatus.GAP, ["Kafka"], found=("Kafka",)))
    assert question == (
        'Do you have experience with this: "Experience with the listed tools"? If yes, '
        "where, and what did you do?"
    )


def test_adjacent_quotes_the_related_line() -> None:
    line = RelatedEvidence(
        span_id="s3",
        text="Streamed order events into the warehouse.",
        section=Section.EXPERIENCE,
        page=1,
        score=0.8,
    )
    with_skill = _match(MatchStatus.ADJACENT, ["Kafka"], related=[line])
    assert question_for(with_skill) == (
        'Have you used Kafka? This line looks related: "Streamed order events into the '
        'warehouse.". If yes, where, and what did you build with it?'
    )
    no_skill = _match(MatchStatus.ADJACENT, [], related=[line])
    question = question_for(no_skill)
    assert question is not None
    assert question.startswith('Does your experience show this: "Experience with the listed')


def test_supported_requirements_get_no_question() -> None:
    for status in (MatchStatus.DIRECT, MatchStatus.PARTIAL, MatchStatus.NOT_ASSESSED):
        assert question_for(_match(status, ["Python"], found=("Python",))) is None


def test_adjacent_from_the_sample(data_engineer_markup: str, data_engineer_jd: str) -> None:
    _, report = analyze(
        build_pdf(data_engineer_markup),
        data_engineer_jd,
        encoder=FakeEncoder(),
        reranker=FakeReranker(),
        today=date(2026, 11, 8),
    )
    mentor = next(q for q in gap_questions(report) if q.requirement_text.startswith("Mentor"))
    assert mentor.status is MatchStatus.ADJACENT
    assert '"Reviewed pull requests for two junior engineers' in mentor.question
