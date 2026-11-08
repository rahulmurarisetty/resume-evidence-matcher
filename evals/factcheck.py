"""The rewrite fact checker against the labeled source and rewrite pairs.

"Adds a fact" is the positive class: the checker rejecting a rewrite is a
positive prediction. A false pass (an adds_fact case the checker let through) is
the dangerous error, because that rewrite would be shown to the person. A false
reject only throws away a good suggestion.
"""

from collections.abc import Sequence
from typing import Any

from app.services.factcheck import check_rewrite
from app.services.skills import SkillCatalog
from evals.dataset import FactCase
from evals.metrics import BinaryCounts, Rate

POSITIVE = "adds_fact"


def evaluate_cases(cases: Sequence[FactCase], catalog: SkillCatalog) -> dict[str, Any]:
    outcomes: list[tuple[FactCase, bool, list[str]]] = []
    for case in cases:
        result = check_rewrite(case.source, case.rewrite, catalog)
        reasons = [fact.reason for fact in result.added]
        outcomes.append((case, not result.passed, reasons))

    counts = BinaryCounts.from_pairs(
        (case.label == POSITIVE, flagged) for case, flagged, _ in outcomes
    )
    categories: dict[str, list[tuple[str, bool]]] = {}
    for case, flagged, _ in outcomes:
        categories.setdefault(case.category, []).append(
            (case.label, flagged == (case.label == POSITIVE))
        )
    per_category = sorted(
        (
            {
                "category": name,
                "label": "/".join(sorted({label for label, _ in rows})),
                "accuracy": Rate(sum(ok for _, ok in rows), len(rows)).to_dict(),
            }
            for name, rows in categories.items()
        ),
        key=lambda row: (row["label"], row["category"]),
    )
    disagreements = [
        {
            "id": case.id,
            "category": case.category,
            "gold": case.label,
            "checker": "rejected" if flagged else "passed",
            "source": case.source,
            "rewrite": case.rewrite,
            "gold_added": list(case.added),
            "checker_reasons": reasons,
        }
        for case, flagged, reasons in outcomes
        if flagged != (case.label == POSITIVE)
    ]
    return {
        "cases": len(cases),
        "adds_fact_cases": counts.tp + counts.fn,
        "faithful_cases": counts.fp + counts.tn,
        "counts": counts.to_dict(),
        "accuracy": counts.accuracy.to_dict(),
        "precision": counts.precision.to_dict(),
        "recall": counts.recall.to_dict(),
        "false_pass_rate": counts.false_negative_rate.to_dict(),
        "false_reject_rate": counts.false_positive_rate.to_dict(),
        "per_category": per_category,
        "disagreements": disagreements,
    }
