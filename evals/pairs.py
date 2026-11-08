"""Evidence and status for each labeled resume and job pair.

The app's statuses map to the label set one to one, with not_assessed read as
needs_check. A labeled requirement the parser didn't extract gets the status
"not_extracted", which always counts as wrong.

Evidence lines are read in the order the report gives them: exact evidence skill
by skill (each skill's demonstrated lines first), then related evidence from
matching by meaning. A line counts once, at its first position.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models import AnalysisReport, RequirementMatch
from evals.dataset import GoldJob, GoldPair
from evals.matching import align_texts, evidence_hit
from evals.metrics import BinaryCounts, ConfusionMatrix, Rate, rate_of

STATUSES = ["direct", "partial", "adjacent", "gap", "needs_check"]
APP_TO_GOLD = {
    "direct": "direct",
    "partial": "partial",
    "adjacent": "adjacent",
    "gap": "gap",
    "not_assessed": "needs_check",
}
NOT_EXTRACTED = "not_extracted"
SUPPORTED = {"direct", "partial", "adjacent"}
UNPROVEN = {"gap", "needs_check"}
FITS = ("strong", "mixed", "wrong")
EVIDENCE_K = (1, 3)


@dataclass(frozen=True)
class EvidenceLine:
    text: str
    section: str
    source: str  # "exact" or "related"
    detail: str  # the matched term, or the reranker score

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "section": self.section,
            "source": self.source,
            "detail": self.detail,
        }


def evidence_lines(match: RequirementMatch) -> list[EvidenceLine]:
    lines: list[EvidenceLine] = []
    seen: set[str] = set()
    for skill in match.skills:
        for evidence in skill.evidence:
            if evidence.span_id in seen:
                continue
            seen.add(evidence.span_id)
            lines.append(
                EvidenceLine(
                    evidence.text,
                    evidence.section.value,
                    "exact",
                    f"{skill.skill} via {evidence.matched_term!r}",
                )
            )
    for related in match.related_evidence:
        if related.span_id in seen:
            continue
        seen.add(related.span_id)
        lines.append(
            EvidenceLine(related.text, related.section.value, "related", f"score {related.score}")
        )
    return lines


@dataclass
class ItemOutcome:
    pair: str
    resume: str
    job: str
    fit: str
    format: str
    mode: str
    text: str
    gold_status: str
    app_status: str
    app_text: str | None
    years_only: bool
    skills: list[str]
    skill_strengths: dict[str, str | None]
    gold_evidence: list[str]
    lines: list[EvidenceLine] = field(default_factory=list)
    hits: dict[int, bool] = field(default_factory=dict)
    years_found: float | None = None
    min_years: int | None = None
    next_action: str = ""

    @property
    def correct(self) -> bool:
        return self.gold_status == self.app_status

    @property
    def evidence_scored(self) -> bool:
        """Counted in evidence recall: a supported label with evidence strings."""
        return self.gold_status in SUPPORTED and bool(self.gold_evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "format": self.format,
            "mode": self.mode,
            "text": self.text,
            "gold": self.gold_status,
            "app": self.app_status,
            "app_text": self.app_text if self.app_text != self.text else None,
            "years_only": self.years_only,
            "skills": {k: v for k, v in self.skill_strengths.items()},
            "min_years": self.min_years,
            "years_found": self.years_found,
            "top_evidence": [line.to_dict() for line in self.lines[:3]],
            "gold_evidence": self.gold_evidence,
        }


def evaluate_pair(
    pair: GoldPair, job: GoldJob, report: AnalysisReport, format_name: str, mode: str
) -> list[ItemOutcome]:
    matches = report.matches
    gold_texts = [r.text for r in job.requirements]
    alignment = align_texts([m.requirement.text for m in matches], gold_texts)
    gold_to_predicted = alignment.gold_to_predicted()
    outcomes: list[ItemOutcome] = []
    for item in pair.items:
        p_index = gold_to_predicted.get(gold_texts.index(item.text))
        match = matches[p_index] if p_index is not None else None
        outcome = ItemOutcome(
            pair=pair.key,
            resume=pair.resume,
            job=pair.job,
            fit=pair.fit,
            format=format_name,
            mode=mode,
            text=item.text,
            gold_status=item.status,
            app_status=NOT_EXTRACTED if match is None else APP_TO_GOLD[match.status.value],
            app_text=None if match is None else match.requirement.text,
            years_only=False,
            skills=[] if match is None else list(match.requirement.skills),
            skill_strengths={}
            if match is None
            else {
                s.skill: (s.strength.value if s.strength is not None else None)
                for s in match.skills
            },
            gold_evidence=list(item.evidence),
        )
        if match is not None:
            requirement = match.requirement
            outcome.years_only = bool(requirement.min_years) and not requirement.skills
            outcome.lines = evidence_lines(match)
            outcome.years_found = match.years_found
            outcome.min_years = requirement.min_years
            outcome.next_action = match.next_action
        texts = [line.text for line in outcome.lines]
        outcome.hits = {k: evidence_hit(texts, item.evidence, k) for k in EVIDENCE_K}
        outcomes.append(outcome)
    return outcomes


def status_matrix() -> ConfusionMatrix:
    return ConfusionMatrix(list(STATUSES), [*STATUSES, NOT_EXTRACTED])


def summarize(items: Sequence[ItemOutcome]) -> dict[str, Any]:
    confusion = status_matrix()
    for item in items:
        confusion.add(item.gold_status, item.app_status)
    gap = BinaryCounts.from_pairs((i.gold_status == "gap", i.app_status == "gap") for i in items)
    unproven = [i for i in items if i.gold_status in UNPROVEN]
    false_proven = [i for i in unproven if i.app_status == "direct"]
    app_direct = [i for i in items if i.app_status == "direct"]
    scored = [i for i in items if i.evidence_scored]
    scored_lines = [i for i in scored if not i.years_only]
    return {
        "items": len(items),
        "status_accuracy": confusion.accuracy.to_dict(),
        "confusion": confusion.to_dict(),
        "per_status": {
            status: {
                "precision": confusion.precision(status).to_dict(),
                "recall": confusion.recall(status).to_dict(),
            }
            for status in STATUSES
        },
        "gap_precision": gap.precision.to_dict(),
        "gap_recall": gap.recall.to_dict(),
        "false_proven_rate": Rate(len(false_proven), len(unproven)).to_dict(),
        "false_proven_share_of_direct": Rate(len(false_proven), len(app_direct)).to_dict(),
        "overclaim_rate": rate_of(
            i.app_status == "direct" for i in items if i.gold_status != "direct"
        ).to_dict(),
        "not_extracted": Rate(
            sum(i.app_status == NOT_EXTRACTED for i in items), len(items)
        ).to_dict(),
        "evidence_recall_at_1": rate_of(i.hits.get(1, False) for i in scored).to_dict(),
        "evidence_recall_at_3": rate_of(i.hits.get(3, False) for i in scored).to_dict(),
        "evidence_recall_at_1_without_years_only": rate_of(
            i.hits.get(1, False) for i in scored_lines
        ).to_dict(),
        "evidence_recall_at_3_without_years_only": rate_of(
            i.hits.get(3, False) for i in scored_lines
        ).to_dict(),
        "status_accuracy_by_fit": {
            fit: rate_of(i.correct for i in items if i.fit == fit).to_dict() for fit in FITS
        },
    }


def per_pair_rows(items: Sequence[ItemOutcome]) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        row = rows.setdefault(
            (item.pair, item.format),
            {"pair": item.pair, "fit": item.fit, "format": item.format, "items": 0, "correct": 0},
        )
        row["items"] += 1
        row["correct"] += item.correct
    return list(rows.values())
