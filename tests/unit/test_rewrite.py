"""Rewrite suggestions: which bullet is chosen, what is sent, and how the fact
checker, the cap and errors shape the result. Claude is a fake throughout."""

import re
from datetime import date

import pytest

from app.llm import LLMError, LLMOutputError, LLMTimeoutError
from app.models import AnalysisReport, ResumeDocument
from app.services.analysis import analyze
from app.services.factcheck import check_rewrite
from app.services.rewrite import (
    RewriteOutput,
    Target,
    choose_targets,
    generate_rewrites,
    rewritable_span_ids,
)
from app.services.skills import SkillCatalog
from tests.builders import build_pdf
from tests.fakes import FakeEncoder, FakeLLMClient, FakeReranker, LLMCall

TODAY = date(2026, 11, 8)


@pytest.fixture(scope="module")
def sample(
    data_engineer_markup: str, data_engineer_jd: str
) -> tuple[ResumeDocument, AnalysisReport]:
    return analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=TODAY)


def _text(resume: ResumeDocument) -> dict[str, str]:
    return {span.id: span.text for span in resume.spans}


def _bullet(call: LLMCall) -> str:
    found = re.search(r"<bullet>\n(.*)\n</bullet>", call.user)
    assert found is not None
    return found.group(1)


def test_only_work_bullets_can_be_rewritten(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = sample
    allowed = rewritable_span_ids(resume, report)
    by_id = {span.id: span for span in resume.spans}
    assert allowed == {"s6", "s7", "s8", "s9", "s10", "s12", "s13", "s14"}
    # The name, contact line, headings, role lines, skills and education never are.
    for span_id in ("s0", "s1", "s4", "s5", "s11", "s16", "s20"):
        assert span_id not in allowed, by_id[span_id].text


def test_bullets_with_contacts_or_dates_are_never_sent() -> None:
    markup = """# Robin Example
## Experience
### Analyst, Example Corp | Jan 2020 - Present
- Built reports in SQL for the finance team every month.
- Portfolio at https://example.com/robin with sample SQL work.
- Ran the 2021 - 2022 migration of reports from Excel to SQL.
"""
    resume, report = analyze(build_pdf(markup), "Requirements\n- Strong SQL\n" * 3, today=TODAY)
    allowed = rewritable_span_ids(resume, report)
    texts = {s.text for s in resume.spans if s.id in allowed}
    assert texts == {"Built reports in SQL for the finance team every month."}


def test_targets_use_the_best_evidence(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = sample
    targets, skipped = choose_targets(report, resume, _text(resume))
    by_requirement = {t.requirement_id: t for t in targets}
    # "Strong Python and SQL": the first work bullet that names Python.
    assert by_requirement["r6"].span_id == "s9"
    assert by_requirement["r6"].source_text.startswith("Wrote Python data-quality checks")
    # Gaps, years-only and not-assessed requirements are not targets.
    assert {"r1", "r5", "r11", "r12"}.isdisjoint(by_requirement)
    # "Git and CI/CD" is only listed in the skills section: no bullet to rewrite.
    assert ("r10", "no_bullet") in {(s.requirement_id, s.reason) for s in skipped}


def test_requested_ids_explain_why_they_are_skipped(
    sample: tuple[ResumeDocument, AnalysisReport],
) -> None:
    resume, report = sample
    targets, skipped = choose_targets(report, resume, _text(resume), ["r5", "r6", "r11"])
    assert [t.requirement_id for t in targets] == ["r6"]
    assert [(s.requirement_id, s.reason) for s in skipped] == [
        ("r5", "years_only"),
        ("r11", "not_eligible"),
    ]


def test_all_eligible_skips_requirements_with_suggestions(
    sample: tuple[ResumeDocument, AnalysisReport],
) -> None:
    resume, report = sample
    targets, skipped = choose_targets(report, resume, _text(resume), None, ["r6"])
    assert "r6" not in {t.requirement_id for t in targets}
    assert ("r6", "already_suggested") in {(s.requirement_id, s.reason) for s in skipped}
    # Asking for it by id still works.
    targets, _ = choose_targets(report, resume, _text(resume), ["r6"], ["r6"])
    assert [t.requirement_id for t in targets] == ["r6"]


def test_corrected_text_is_the_source(sample: tuple[ResumeDocument, AnalysisReport]) -> None:
    resume, report = sample
    text = _text(resume) | {"s9": "Wrote Python data quality checks for every load."}
    targets, _ = choose_targets(report, resume, text, ["r6"])
    assert targets[0].source_text == "Wrote Python data quality checks for every load."


def test_adjacent_requirements_use_the_related_line(
    data_engineer_markup: str, data_engineer_jd: str
) -> None:
    resume, report = analyze(
        build_pdf(data_engineer_markup),
        data_engineer_jd,
        encoder=FakeEncoder(),
        reranker=FakeReranker(),
        today=TODAY,
    )
    mentor = next(m for m in report.matches if m.requirement.text.startswith("Mentor"))
    assert mentor.status.value == "adjacent"
    targets, _ = choose_targets(report, resume, _text(resume), [mentor.requirement.id])
    assert targets[0].source_text.startswith("Reviewed pull requests for two junior engineers")


SOURCE = (
    "Scheduled and monitored 40+ Airflow DAGs, adding SLA alerts that reduced missed "
    "morning loads from weekly to roughly once a quarter."
)
FAITHFUL = (
    "Orchestrated 40+ Airflow DAGs with SLA alerts, reducing missed morning loads from "
    "weekly to roughly once a quarter."
)
INVENTED = (
    "Orchestrated 400+ Airflow DAGs with SLA alerts, reducing missed morning loads from "
    "weekly to roughly once a quarter."
)


def _target(requirement_id: str = "r2", span_id: str = "s8", source: str = SOURCE) -> Target:
    return Target(
        requirement_id,
        "Orchestrate workflows with Airflow and keep them observable",
        span_id,
        source,
    )


def test_survivors_pass_the_fact_checker(catalog: SkillCatalog) -> None:
    client = FakeLLMClient(RewriteOutput(rewrites=[FAITHFUL, INVENTED]), model="claude-sonnet-5-5")
    run = generate_rewrites([_target()], client=client, model="claude-sonnet-5-5", budget=20)

    assert [c.text for c in run.kept] == [FAITHFUL]
    assert run.rejected == 1
    assert (run.calls, run.requested, run.returned) == (1, 2, 2)
    assert run.prompt_version == "rewrite_v1"
    assert run.model == "claude-sonnet-5-5"
    assert (run.input_tokens, run.output_tokens) == (120, 40)
    for candidate in run.kept:
        assert check_rewrite(candidate.source_text, candidate.text, catalog).passed
        assert (candidate.requirement_id, candidate.span_id) == ("r2", "s8")

    [call] = client.calls
    assert call.output_type is RewriteOutput
    assert call.prompt_version == "rewrite_v1"
    assert call.system.startswith("# Resume bullet rewriter, version 1")
    assert "<requirement>\nOrchestrate workflows with Airflow" in call.user
    assert _bullet(call) == SOURCE
    assert call.user.endswith("Suggest at most 2 rewrites of the bullet.")


def test_unchanged_empty_and_repeated_candidates_are_dropped() -> None:
    rewrites = [SOURCE, "  ", f"- {FAITHFUL}", FAITHFUL.upper()]
    client = FakeLLMClient(RewriteOutput(rewrites=rewrites))
    run = generate_rewrites([_target()], client=client, model="m", budget=20)
    # Only two candidates are read (the most asked for), and both add nothing.
    assert run.kept == [] and run.rejected == 0 and run.unchanged == 2

    client = FakeLLMClient(RewriteOutput(rewrites=[f"- {FAITHFUL}", FAITHFUL.upper()]))
    run = generate_rewrites([_target()], client=client, model="m", budget=20)
    assert [c.text for c in run.kept] == [FAITHFUL]  # the bullet glyph is removed
    assert run.unchanged == 1

    client = FakeLLMClient(RewriteOutput(rewrites=[FAITHFUL]))
    run = generate_rewrites(
        [_target()], client=client, model="m", budget=20, existing={"s8": [FAITHFUL]}
    )
    assert run.kept == [] and run.unchanged == 1


def _asked(call: LLMCall) -> int:
    found = re.search(r"at most (\d+) rewrites", call.user)
    assert found is not None
    return int(found.group(1))


def test_the_cap_limits_what_is_asked() -> None:
    def handler(call: LLMCall) -> RewriteOutput:
        wanted = _asked(call)
        return RewriteOutput(
            rewrites=[
                f"Orchestrated Airflow DAGs, version {chr(65 + i)}." for i in range(wanted + 3)
            ]
        )

    client = FakeLLMClient(handler=handler)
    targets = [_target(f"r{i}", f"s{i}", "Scheduled Airflow DAGs.") for i in range(4)]
    run = generate_rewrites(targets, client=client, model="m", budget=3)
    assert run.requested == 3
    assert run.returned == 3  # extra candidates beyond the ask are ignored
    assert [_asked(c) for c in client.calls] == [2, 1]
    assert [(s.requirement_id, s.reason) for s in run.skipped] == [
        ("r2", "limit_reached"),
        ("r3", "limit_reached"),
    ]


def test_a_timeout_stops_the_run() -> None:
    client = FakeLLMClient(LLMTimeoutError("slow"), RewriteOutput(rewrites=[FAITHFUL]))
    run = generate_rewrites(
        [_target("r1"), _target("r2"), _target("r3")], client=client, model="m", budget=20
    )
    assert len(client.calls) == 1
    assert run.requested == 0
    assert [(s.requirement_id, s.reason) for s in run.skipped] == [
        ("r1", "timeout"),
        ("r2", "not_attempted"),
        ("r3", "not_attempted"),
    ]


def test_an_api_error_stops_the_run() -> None:
    client = FakeLLMClient(LLMError("down"))
    run = generate_rewrites([_target("r1"), _target("r2")], client=client, model="m", budget=20)
    assert [s.reason for s in run.skipped] == ["api_error", "not_attempted"]


def test_invalid_output_counts_and_moves_on() -> None:
    client = FakeLLMClient(LLMOutputError("bad"), {"rewrites": [FAITHFUL]})
    run = generate_rewrites([_target("r1"), _target("r2")], client=client, model="m", budget=20)
    assert run.requested == 4  # the failed call was paid for
    assert [s.reason for s in run.skipped] == ["invalid_output"]
    assert [c.requirement_id for c in run.kept] == ["r2"]
