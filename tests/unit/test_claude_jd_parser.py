"""The Claude job-description parser with a fake client: output checks, catalog
mapping, free-text skills, and the fallback to the rule parser."""

from typing import Any

import pytest

from app.llm import LLMError, LLMOutputError, LLMTimeoutError
from app.models import (
    JobParserName,
    MatchMode,
    MatchStatus,
    Priority,
    Seniority,
)
from app.services.analysis import analyze
from app.services.claude_jd_parser import ClaudeJobOutput, ClaudeJobParser
from app.services.jd_parser import RuleJobParser
from app.services.skills import SkillCatalog
from tests.builders import build_pdf
from tests.fakes import FakeLLMClient

JD = """Senior Data Engineer

What you'll do
- Design and build batch data pipelines on Databricks and Snowflake
- Partner with analysts to define metrics and data contracts

Requirements
- 5+ years of experience in data engineering
- Strong Python and SQL
- Experience with Apache Kafka or Pulsar
- Experience with Soda Core for data quality

Benefits
- 401(k) with 4% match
"""


def _req(text: str, priority: str, skills: list[str], **extra: Any) -> dict[str, Any]:
    return {"text": text, "priority": priority, "skills": skills, **extra}


VALID = {
    "title": "Senior Data Engineer",
    "seniority": "senior",
    "requirements": [
        _req(
            "Design and build batch data pipelines on Databricks and Snowflake",
            "context",
            ["Databricks", "Snowflake"],
        ),
        _req(
            "Partner with analysts to define metrics and data contracts",
            "context",
            ["data contracts"],
        ),
        _req("5+ years of experience in data engineering", "required", [], min_years=5),
        _req("Strong Python and SQL", "required", ["Python", "SQL"]),
        _req(
            "Experience with Apache Kafka or Pulsar",
            "required",
            ["Apache Kafka", "Pulsar"],
            match_mode="any",
        ),
        _req(
            "Experience with Soda Core for data quality",
            "preferred",
            ["Soda Core"],
        ),
    ],
}


def _parse(catalog: SkillCatalog, *responses: object) -> tuple[Any, FakeLLMClient]:
    client = FakeLLMClient(*responses, model="claude-haiku-5-5")
    parsed = ClaudeJobParser(client, "claude-haiku-5-5").parse(JD, catalog)
    return parsed, client


def test_valid_output_becomes_the_job(catalog: SkillCatalog) -> None:
    parsed, client = _parse(catalog, VALID)
    job = parsed.job
    assert job.title == "Senior Data Engineer"
    assert job.seniority is Seniority.SENIOR
    assert job.min_years == 5
    assert [r.id for r in job.requirements] == [f"r{i}" for i in range(6)]
    by_text = {r.text: r for r in job.requirements}
    assert by_text["Strong Python and SQL"].priority is Priority.REQUIRED
    assert by_text["Experience with Soda Core for data quality"].priority is (Priority.PREFERRED)
    assert by_text["5+ years of experience in data engineering"].min_years == 5
    # Benefits are left out.
    assert all("401(k)" not in r.text for r in job.requirements)

    assert parsed.parser.name is JobParserName.CLAUDE
    assert parsed.parser.prompt_version == "jd_parse_v1"
    assert parsed.parser.model == "claude-haiku-5-5"
    assert parsed.parser.fallback_reason is None
    assert parsed.warnings == []

    [call] = client.calls
    assert call.output_type is ClaudeJobOutput
    assert call.model == "claude-haiku-5-5"
    assert call.prompt_version == "jd_parse_v1"
    assert call.system.startswith("# Job description parser, version 1")
    assert call.user == f"<job_description>\n{JD}\n</job_description>"


def test_skills_map_to_the_catalog(catalog: SkillCatalog) -> None:
    job = _parse(catalog, VALID)[0].job
    kafka = next(r for r in job.requirements if "Kafka" in r.text)
    # "Apache Kafka" is the catalog's Kafka; Pulsar isn't in the catalog.
    assert kafka.skills == ["Kafka", "Pulsar"]
    assert kafka.free_text_skills == ["Pulsar"]
    assert kafka.match_mode is MatchMode.ANY
    python = next(r for r in job.requirements if r.text == "Strong Python and SQL")
    assert python.skills == ["Python", "SQL"]
    assert python.free_text_skills == []


def test_free_text_skills_keep_the_requirement_spelling(catalog: SkillCatalog) -> None:
    output = {
        "requirements": [
            _req(
                "Experience with Soda Core for data quality",
                "required",
                ["soda core"],
            ),
        ]
    }
    [req] = _parse(catalog, output)[0].job.requirements
    assert req.skills == ["Soda Core"]
    assert req.free_text_skills == ["Soda Core"]


def test_skills_not_named_in_the_text_are_dropped(catalog: SkillCatalog) -> None:
    output = {
        "requirements": [
            _req(
                "Experience with Soda Core for data quality",
                "required",
                ["Soda Core", "Monte Carlo", "dbt"],
            ),
        ]
    }
    [req] = _parse(catalog, output)[0].job.requirements
    # Neither a free-text skill nor a catalog skill may be invented.
    assert req.skills == ["Soda Core"]
    assert req.free_text_skills == ["Soda Core"]


def test_catalog_skills_claude_missed_are_added(catalog: SkillCatalog) -> None:
    output = {"requirements": [_req("Strong Python and SQL", "required", [])]}
    [req] = _parse(catalog, output)[0].job.requirements
    assert req.skills == ["Python", "SQL"]


def test_invented_requirement_text_is_dropped(catalog: SkillCatalog) -> None:
    output = {
        "title": "Senior Data Engineer",
        "requirements": [
            _req("Strong Python and SQL", "required", ["Python", "SQL"]),
            _req("Experience with Terraform and AWS", "required", ["Terraform", "AWS"]),
            _req("Strong Python and SQL skills", "required", ["Python"]),
        ],
    }
    parsed, _ = _parse(catalog, output)
    assert [r.text for r in parsed.job.requirements] == ["Strong Python and SQL"]
    assert parsed.parser.dropped_requirements == 2
    assert parsed.warnings == [
        "Claude returned 2 requirements whose text isn't in the job description, so they "
        "were left out."
    ]


def test_whitespace_and_bullets_are_normalized(catalog: SkillCatalog) -> None:
    output = {
        "requirements": [
            _req("-  Strong   Python\nand SQL", "required", ["Python"]),
            _req("Strong Python and SQL", "required", ["Python"]),  # a repeat
        ]
    }
    parsed, _ = _parse(catalog, output)
    assert [r.text for r in parsed.job.requirements] == ["Strong Python and SQL"]
    assert parsed.parser.dropped_requirements == 0


def test_years_must_be_stated_in_the_requirement(catalog: SkillCatalog) -> None:
    output = {
        "requirements": [
            _req("5+ years of experience in data engineering", "required", [], min_years=7),
            _req("Strong Python and SQL", "required", ["Python"], min_years=3),
        ]
    }
    years = {r.text: r.min_years for r in _parse(catalog, output)[0].job.requirements}
    assert years == {
        "5+ years of experience in data engineering": 5,  # the text's number wins
        "Strong Python and SQL": None,
    }


def test_title_must_be_in_the_text(catalog: SkillCatalog) -> None:
    output = {
        "title": "Principal Data Architect",
        "seniority": "unknown",
        "requirements": [_req("5+ years of experience in data engineering", "required", [])],
    }
    job = _parse(catalog, output)[0].job
    assert job.title == "Senior Data Engineer"  # the rule parser's title
    assert job.seniority is Seniority.SENIOR  # worked out from the title, as the rules do


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (LLMTimeoutError("slow"), "timeout"),
        (LLMError("down"), "api_error"),
        ({"requirements": "not a list"}, "invalid_output"),
        (LLMOutputError("no tool call"), "invalid_output"),
        (
            {"requirements": [_req("Nothing like this is in the posting", "required", [])]},
            "invalid_output",
        ),
    ],
    ids=["timeout", "api-error", "invalid-json", "no-tool-call", "nothing-valid"],
)
def test_falls_back_to_the_rules(catalog: SkillCatalog, response: object, reason: str) -> None:
    parsed, client = _parse(catalog, response)
    rules = RuleJobParser().parse(JD, catalog)
    assert parsed.job == rules.job
    assert parsed.parser.name is JobParserName.RULES
    assert parsed.parser.fallback_reason == reason
    assert parsed.parser.prompt_version is None
    assert len(parsed.warnings) == 1
    assert "rule-based parser" in parsed.warnings[0]
    assert len(client.calls) == 1


def test_parser_is_recorded_in_the_report(catalog: SkillCatalog) -> None:
    resume = """# Casey Sample
casey@example.com

## Experience
### Data Engineer, Example Corp | Jan 2018 - Present
- Wrote soda core suites in Python and SQL for every nightly load.
- Built Databricks jobs that load claims data into Snowflake.
"""
    client = FakeLLMClient(VALID)
    _, report = analyze(build_pdf(resume), JD, job_parser=ClaudeJobParser(client, "m"))
    assert report.job_parser.name is JobParserName.CLAUDE
    assert report.job_parser.prompt_version == "jd_parse_v1"
    # The free-text skill is matched in the resume as a phrase, ignoring case.
    match = next(m for m in report.matches if "Soda Core" in m.requirement.text)
    assert match.status is MatchStatus.DIRECT
    assert match.skills[0].evidence[0].matched_term == "soda core"
    pulsar = next(m for m in report.matches if "Kafka" in m.requirement.text)
    assert pulsar.status is MatchStatus.GAP

    _, fallback = analyze(
        build_pdf(resume), JD, job_parser=ClaudeJobParser(FakeLLMClient(LLMTimeoutError("x")), "m")
    )
    assert fallback.job_parser.name is JobParserName.RULES
    assert fallback.job_parser.fallback_reason == "timeout"
    assert any("rule-based parser" in w for w in fallback.warnings)

    _, rules = analyze(build_pdf(resume), JD)
    assert rules.job_parser.name is JobParserName.RULES
    assert rules.job_parser.fallback_reason is None


TERMS_JD = """Mobile Developer

We are looking for a seasoned mobile developer to join our member app team.

Requirements
- Strong Kotlin and Swift
- Only W2 candidates, no C2C.
"""


def test_claude_output_follows_the_terms_and_intro_rules(catalog: SkillCatalog) -> None:
    """Claude labels the intro required and the W2 line a requirement; the checks
    make the intro context, drop the W2 line, and list the rule parser's terms."""
    output = {
        "title": "Mobile Developer",
        "requirements": [
            _req(
                "We are looking for a seasoned mobile developer to join our member app team.",
                "required",
                [],
            ),
            _req("Strong Kotlin and Swift", "required", ["Kotlin", "Swift"]),
            _req("Only W2 candidates, no C2C.", "required", []),
        ],
    }
    client = FakeLLMClient(output, model="claude-haiku-5-5")
    job = ClaudeJobParser(client, "claude-haiku-5-5").parse(TERMS_JD, catalog).job
    assert [(r.text, r.priority) for r in job.requirements] == [
        (
            "We are looking for a seasoned mobile developer to join our member app team.",
            Priority.CONTEXT,
        ),
        ("Strong Kotlin and Swift", Priority.REQUIRED),
    ]
    assert job.employment_terms == ["Only W2 candidates, no C2C."]
