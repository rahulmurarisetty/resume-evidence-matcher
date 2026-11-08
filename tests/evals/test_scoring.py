"""Each evaluation's scoring on small hand-made inputs."""

from datetime import date

import pymupdf

from app.models import (
    Evidence,
    EvidenceStrength,
    JobDescription,
    MatchStatus,
    Priority,
    RelatedEvidence,
    Requirement,
    RequirementMatch,
    Section,
    Seniority,
    SkillMatch,
)
from app.services.extraction import extract_resume
from app.services.skills import SkillCatalog
from app.services.structure import parse_profile
from evals import errors, pairs, requirements, resume_structure
from evals.dataset import FactCase, GoldJob, GoldRequirement, GoldResume, GoldRole
from evals.factcheck import evaluate_cases
from evals.pairs import ItemOutcome, evidence_lines, summarize
from tests.builders import build_docx

AS_OF = date(2026, 11, 1)


def _item(gold: str, app: str, **kwargs: object) -> ItemOutcome:
    fields: dict[str, object] = {
        "pair": "r x j",
        "resume": "r",
        "job": "j",
        "fit": "strong",
        "format": "docx",
        "mode": "exact",
        "text": f"{gold} {app}",
        "gold_status": gold,
        "app_status": app,
        "app_text": None,
        "years_only": False,
        "skills": [],
        "skill_strengths": {},
        "gold_evidence": [],
    }
    fields.update(kwargs)
    return ItemOutcome(**fields)  # type: ignore[arg-type]


def test_pair_summary_status_gap_and_false_proven() -> None:
    items = [
        _item("direct", "direct"),
        _item("direct", "partial"),
        _item("gap", "gap"),
        _item("gap", "direct"),  # false proven
        _item("needs_check", "needs_check"),
        _item("needs_check", "gap"),
        _item("partial", "not_extracted"),
    ]
    summary = summarize(items)
    assert summary["status_accuracy"] == {"rate": 0.4286, "count": 3, "total": 7}
    # gap: predicted gap twice, once right; labeled gap twice, found once
    assert summary["gap_precision"]["count"] == 1 and summary["gap_precision"]["total"] == 2
    assert summary["gap_recall"]["count"] == 1 and summary["gap_recall"]["total"] == 2
    # labeled gap or needs_check: 4 items, one called direct
    assert summary["false_proven_rate"] == {"rate": 0.25, "count": 1, "total": 4}
    assert summary["false_proven_share_of_direct"] == {"rate": 0.5, "count": 1, "total": 2}
    assert summary["not_extracted"]["count"] == 1
    rows = summary["confusion"]["rows"]
    labels = summary["confusion"]["predicted_labels"]
    assert labels[-1] == "not_extracted"
    partial_row = rows[summary["confusion"]["gold_labels"].index("partial")]
    assert partial_row[labels.index("not_extracted")] == 1


def test_pair_summary_evidence_recall_counts_only_supported_items_with_evidence() -> None:
    items = [
        _item("direct", "direct", gold_evidence=["a"], hits={1: True, 3: True}),
        _item("direct", "direct", gold_evidence=["b"], hits={1: False, 3: True}),
        _item(
            "direct",
            "direct",
            gold_evidence=["role line"],
            hits={1: False, 3: False},
            years_only=True,
        ),
        _item("adjacent", "gap", gold_evidence=["c"], hits={1: False, 3: False}),
        _item("gap", "gap", gold_evidence=[], hits={1: False, 3: False}),
        _item("direct", "direct", gold_evidence=[], hits={1: False, 3: False}),
    ]
    summary = summarize(items)
    assert summary["evidence_recall_at_1"] == {"rate": 0.25, "count": 1, "total": 4}
    assert summary["evidence_recall_at_3"] == {"rate": 0.5, "count": 2, "total": 4}
    assert summary["evidence_recall_at_3_without_years_only"]["total"] == 3
    assert summary["evidence_recall_at_3_without_years_only"]["count"] == 2


def _evidence(span_id: str, text: str, skill_term: str, strength: EvidenceStrength) -> Evidence:
    return Evidence(
        span_id=span_id,
        text=text,
        section=Section.EXPERIENCE,
        page=None,
        matched_term=skill_term,
        strength=strength,
    )


def test_evidence_lines_are_exact_skill_by_skill_then_related_without_repeats() -> None:
    demonstrated = EvidenceStrength.DEMONSTRATED
    match = RequirementMatch(
        requirement=_requirement(1, "Python and SQL", Priority.REQUIRED),
        status=MatchStatus.DIRECT,
        skills=[
            SkillMatch(
                skill="Python",
                strength=demonstrated,
                evidence=[
                    _evidence("s1", "Python and SQL ETL", "Python", demonstrated),
                    _evidence("s2", "Python tooling", "Python", demonstrated),
                ],
            ),
            SkillMatch(
                skill="SQL",
                strength=demonstrated,
                evidence=[_evidence("s1", "Python and SQL ETL", "SQL", demonstrated)],
            ),
        ],
        related_evidence=[
            RelatedEvidence(
                span_id="s2", text="Python tooling", section=Section.EXPERIENCE, page=1, score=0.9
            ),
            RelatedEvidence(
                span_id="s3", text="Wrote reports", section=Section.EXPERIENCE, page=1, score=0.6
            ),
        ],
        next_action="",
    )
    lines = evidence_lines(match)
    texts = [line.text for line in lines]
    assert texts == ["Python and SQL ETL", "Python tooling", "Wrote reports"]
    assert [line.source for line in lines] == ["exact", "exact", "related"]


def _job(*lines: tuple[str, str]) -> GoldJob:
    return GoldJob(
        name="j",
        text="",
        title="Data Engineer",
        min_years=5,
        requirements=tuple(GoldRequirement(text, priority) for text, priority in lines),
    )


def _requirement(i: int, text: str, priority: Priority) -> Requirement:
    return Requirement(id=f"r{i}", text=text, priority=priority, skills=[])


def test_requirement_extraction_precision_recall_and_classes() -> None:
    gold = _job(
        ("5+ years of experience", "required"),
        ("Strong Python skills", "required"),
        ("Experience with dbt", "preferred"),
        ("Mentor junior engineers", "context"),
    )
    parsed = JobDescription(
        title="Data Engineer",
        seniority=Seniority.SENIOR,
        min_years=3,
        requirements=[
            _requirement(0, "5+ years of experience.", Priority.REQUIRED),
            _requirement(1, "Strong Python skills", Priority.CONTEXT),
            _requirement(2, "Experience with dbt is a plus", Priority.PREFERRED),
            _requirement(3, "What we offer", Priority.PREFERRED),
        ],
    )
    result = requirements.evaluate_job(gold, parsed, "rules")
    assert (result.gold_count, result.predicted_count, result.matched_count) == (4, 4, 3)
    assert result.priority_correct == 2
    assert result.match_kinds == {"exact": 2, "contains": 1}
    assert result.title_ok and not result.min_years_ok
    assert [s["text"] for s in result.spurious] == ["What we offer"]
    assert [m["text"] for m in result.missed] == ["Mentor junior engineers"]

    summary = requirements.summarize([result])
    assert summary["extraction_precision"]["count"] == 3
    assert summary["extraction_recall"] == {"rate": 0.75, "count": 3, "total": 4}
    assert summary["priority_accuracy"] == {"rate": 0.6667, "count": 2, "total": 3}
    per_class = summary["per_class"]
    assert per_class["required"]["precision"] == {"rate": 1.0, "count": 1, "total": 1}
    assert per_class["required"]["recall"] == {"rate": 0.5, "count": 1, "total": 2}
    # preferred: one right, one spurious "What we offer"
    assert per_class["preferred"]["precision"] == {"rate": 0.5, "count": 1, "total": 2}
    # context: the only context prediction was really required; the labeled one was missed
    assert per_class["context"]["precision"]["count"] == 0
    assert per_class["context"]["recall"] == {"rate": 0.0, "count": 0, "total": 1}
    assert summary["min_years_accuracy"] == {"rate": 0.0, "count": 0, "total": 1}


def test_fact_checker_scoring_and_disagreements(catalog: SkillCatalog) -> None:
    cases = [
        FactCase("a", "Built 5 dashboards.", "Built 50 dashboards.", "adds_fact", ("50",), "num"),
        FactCase("b", "Built 5 dashboards.", "Built five dashboards.", "faithful", (), "tricky"),
        # Mislabeled on purpose: the checker passes it, so it counts as a false pass.
        FactCase("c", "Built 5 dashboards.", "Built 5 dashboards.", "adds_fact", ("x",), "num"),
    ]
    result = evaluate_cases(cases, catalog)
    assert result["counts"] == {"tp": 1, "fp": 0, "tn": 1, "fn": 1}
    assert result["false_pass_rate"] == {"rate": 0.5, "count": 1, "total": 2}
    assert result["false_reject_rate"] == {"rate": 0.0, "count": 0, "total": 1}
    assert [d["id"] for d in result["disagreements"]] == ["c"]
    assert result["disagreements"][0]["checker"] == "passed"
    by_category = {row["category"]: row for row in result["per_category"]}
    assert by_category["num"]["accuracy"] == {"rate": 0.5, "count": 1, "total": 2}


# Two layouts the app still reads wrongly: no separator between the title and the
# employer, and a role written as a sentence.
MARKUP = """# Pat Example
## Experience
### Data Engineer Example Corp | Mar 2022 - Present
- Built Python pipelines.
Worked as an Analyst at Demo Labs from Jan 2019 - Feb 2022.
- Wrote SQL reports.
### Intern, Sample Co | 2018 - 2018
- Fixed bugs.
## Education
### B.S. Computer Science, Example University, 2018
"""

GOLD = GoldResume(
    name="r",
    markup=MARKUP,
    as_of=AS_OF,
    roles=(
        GoldRole("Data Engineer", "Example Corp", "2022-03", None),
        GoldRole("Analyst", "Demo Labs", "2019-01", "2022-02"),
        GoldRole("Intern", "Sample Co", "2018-01", "2018-12"),
    ),
    total_years=8.8,
    education=(),
)


def test_structure_scoring_and_diagnoses() -> None:
    document = extract_resume(build_docx(MARKUP))
    profile = parse_profile(document, today=AS_OF)
    result = resume_structure.evaluate_resume(GOLD, document, profile, "docx")
    assert (result.gold_roles, result.matched_roles) == (3, 1)
    assert result.start_correct == result.end_correct == 1
    causes = {item.gold["employer"]: item.cause for item in result.missed_roles}
    assert causes == {"Example Corp": "fields_differ", "Demo Labs": "not_a_header"}
    # v1.0: a name ending in a company suffix ("Corp") is an employer, never a title,
    # so the unsplit line is now read as the employer (it used to be the title).
    predicted = result.extra_roles[0]["predicted"]
    assert (predicted["title"], predicted["employer"]) == (None, "Data Engineer Example Corp")
    assert result.years_error is not None
    # Education isn't labeled for this resume, so the parsed degree is an extra entry.
    summary = resume_structure.summarize([result])
    assert summary["role_recall"] == {"rate": 0.3333, "count": 1, "total": 3}
    assert summary["role_precision"]["total"] == 2
    assert summary["education_precision"] == {"rate": 0.0, "count": 0, "total": 1}


def test_structure_diagnoses_changed_characters_in_pdf_dates() -> None:
    markup = "# Pat Example\n## Experience\n### Engineer at Example Corp, Mar 2022 \u2013 Present\n"
    gold = GoldResume(
        "r", markup, AS_OF, (GoldRole("Engineer", "Example Corp", "2022-03", None),), 4.7, ()
    )
    # tests/builders.py keeps the en dash since v0.5, so this PDF is written with a
    # base-14 font, which turns it into a middle dot, as the builder used to.
    pdf = pymupdf.open()
    page = pdf.new_page()
    for y, line in ((72, "Pat Example"), (100, "EXPERIENCE"), (120, markup.splitlines()[2][4:])):
        page.insert_text((72, y), line, fontname="helv", fontsize=10.5)
    document = extract_resume(pdf.tobytes())
    profile = parse_profile(document, today=AS_OF)
    result = resume_structure.evaluate_resume(gold, document, profile, "pdf_inline")
    assert result.matched_roles == 1
    [error] = result.date_errors
    assert error.cause == "dates_unreadable"
    assert "'\u2013' became '\u00b7'" in error.detail


def test_error_patterns_count_distinct_items_and_name_formats() -> None:
    items = [
        _item("direct", "needs_check", format="docx", text="Experience with Next.js"),
        _item("direct", "needs_check", format="pdf_inline", text="Experience with Next.js"),
        _item("gap", "needs_check", format="docx", text="ISTQB certification"),
    ]
    found = errors.find_patterns(
        structure=[],
        requirements=[],
        items=items,
        factcheck={},
        formats=["pdf_inline", "docx"],
    )
    [pattern] = found
    assert pattern["id"] == "pair_no_catalog_skill"
    assert pattern["count"] == 2
    assert pattern["formats"] == "all formats"
    assert pattern["examples"][0]["formats"] == "all formats"
    assert pattern["examples"][1]["formats"] == "docx"


def test_status_mapping_covers_every_app_status() -> None:
    assert set(pairs.APP_TO_GOLD) == {status.value for status in MatchStatus}
    assert set(pairs.APP_TO_GOLD.values()) == set(pairs.STATUSES)
