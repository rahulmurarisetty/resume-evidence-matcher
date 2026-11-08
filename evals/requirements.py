"""Requirement extraction from job descriptions.

Predicted requirement texts are aligned one to one with the labeled lines (exact,
containment or fuzzy match after normalizing case, whitespace and punctuation).
A prediction with no label is "not a requirement" (benefits, company intro or
boilerplate the parser kept), and a label with no prediction is "not extracted".
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models import JobDescription
from evals.dataset import GoldJob
from evals.matching import align_texts, field_score, text_match
from evals.metrics import ConfusionMatrix, Rate, pooled, rate_of

PRIORITIES = ["required", "preferred", "context"]
NOT_EXTRACTED = "not_extracted"
NOT_A_REQUIREMENT = "not_a_requirement"


def priority_matrix() -> ConfusionMatrix:
    return ConfusionMatrix([*PRIORITIES, NOT_A_REQUIREMENT], [*PRIORITIES, NOT_EXTRACTED])


@dataclass
class JobExtraction:
    job: str
    parser: str
    gold_count: int
    predicted_count: int
    matched_count: int
    priority_correct: int
    confusion: ConfusionMatrix
    title_gold: str
    title_predicted: str | None
    min_years_gold: int | None
    min_years_predicted: int | None
    match_kinds: Counter[str] = field(default_factory=Counter)
    spurious: list[dict[str, Any]] = field(default_factory=list)
    missed: list[dict[str, Any]] = field(default_factory=list)
    priority_errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def title_ok(self) -> bool:
        return field_score(self.title_predicted, self.title_gold) is not None

    @property
    def min_years_ok(self) -> bool:
        return self.min_years_predicted == self.min_years_gold


def evaluate_job(gold: GoldJob, parsed: JobDescription, parser: str) -> JobExtraction:
    predicted = parsed.requirements
    gold_texts = [r.text for r in gold.requirements]
    alignment = align_texts([r.text for r in predicted], gold_texts)
    confusion = priority_matrix()
    result = JobExtraction(
        job=gold.name,
        parser=parser,
        gold_count=len(gold.requirements),
        predicted_count=len(predicted),
        matched_count=len(alignment.matched),
        priority_correct=0,
        confusion=confusion,
        title_gold=gold.title,
        title_predicted=parsed.title,
        min_years_gold=gold.min_years,
        min_years_predicted=parsed.min_years,
    )
    for p_index, g_index, _ in alignment.matched:
        requirement, expected = predicted[p_index], gold.requirements[g_index]
        found = text_match(requirement.text, expected.text)
        if found is not None:
            result.match_kinds[found.kind.value] += 1
        confusion.add(expected.priority, requirement.priority.value)
        if requirement.priority.value == expected.priority:
            result.priority_correct += 1
        else:
            result.priority_errors.append(
                {
                    "job": gold.name,
                    "text": expected.text,
                    "gold": expected.priority,
                    "predicted": requirement.priority.value,
                }
            )
    for g_index in alignment.unmatched_gold:
        expected = gold.requirements[g_index]
        confusion.add(expected.priority, NOT_EXTRACTED)
        result.missed.append({"job": gold.name, "text": expected.text, "gold": expected.priority})
    for p_index in alignment.unmatched_predicted:
        requirement = predicted[p_index]
        confusion.add(NOT_A_REQUIREMENT, requirement.priority.value)
        result.spurious.append(
            {"job": gold.name, "text": requirement.text, "predicted": requirement.priority.value}
        )
    return result


def summarize(results: Sequence[JobExtraction]) -> dict[str, Any]:
    confusion = priority_matrix()
    for result in results:
        confusion.merge(result.confusion)
    matched = sum(r.matched_count for r in results)
    kinds: Counter[str] = Counter()
    for result in results:
        kinds.update(result.match_kinds)
    return {
        "jobs": len(results),
        "extraction_precision": Rate(matched, sum(r.predicted_count for r in results)).to_dict(),
        "extraction_recall": Rate(matched, sum(r.gold_count for r in results)).to_dict(),
        "priority_accuracy": pooled(
            Rate(r.priority_correct, r.matched_count) for r in results
        ).to_dict(),
        "per_class": {
            label: {
                "precision": confusion.precision(label).to_dict(),
                "recall": confusion.recall(label).to_dict(),
            }
            for label in PRIORITIES
        },
        "confusion": confusion.to_dict(),
        "min_years_accuracy": rate_of(r.min_years_ok for r in results).to_dict(),
        "title_accuracy": rate_of(r.title_ok for r in results).to_dict(),
        "match_kinds": {kind: kinds[kind] for kind in ("exact", "contains", "fuzzy")},
    }


def per_job_rows(results: Sequence[JobExtraction]) -> list[dict[str, Any]]:
    return [
        {
            "job": r.job,
            "gold": r.gold_count,
            "predicted": r.predicted_count,
            "matched": r.matched_count,
            "priority_correct": r.priority_correct,
            "min_years_gold": r.min_years_gold,
            "min_years_app": r.min_years_predicted,
            "title_ok": r.title_ok,
        }
        for r in results
    ]
