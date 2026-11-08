"""Counting helpers. Every rate keeps its counts, so a reader always sees the
sample size next to the number."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

ROUND = 4


def rounded(value: float | None, digits: int = ROUND) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class Rate:
    count: int
    total: int

    @property
    def value(self) -> float | None:
        return self.count / self.total if self.total else None

    def __add__(self, other: "Rate") -> "Rate":
        return Rate(self.count + other.count, self.total + other.total)

    def to_dict(self) -> dict[str, Any]:
        return {"rate": rounded(self.value), "count": self.count, "total": self.total}

    def __str__(self) -> str:
        value = self.value
        shown = "n/a" if value is None else f"{value * 100:.1f}%"
        return f"{shown} ({self.count}/{self.total})"


def rate_of(flags: Iterable[bool]) -> Rate:
    values = list(flags)
    return Rate(sum(values), len(values))


def pooled(rates: Iterable[Rate]) -> Rate:
    total = Rate(0, 0)
    for item in rates:
        total = total + item
    return total


@dataclass(frozen=True)
class BinaryCounts:
    """Counts for a yes/no decision. "Positive" is the class the caller cares about
    finding (an added fact, a gap)."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[bool, bool]]) -> "BinaryCounts":
        """`pairs` holds (gold is positive, predicted positive)."""
        tp = fp = tn = fn = 0
        for gold, predicted in pairs:
            if gold and predicted:
                tp += 1
            elif predicted:
                fp += 1
            elif gold:
                fn += 1
            else:
                tn += 1
        return cls(tp, fp, tn, fn)

    @property
    def accuracy(self) -> Rate:
        return Rate(self.tp + self.tn, self.tp + self.fp + self.tn + self.fn)

    @property
    def precision(self) -> Rate:
        return Rate(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Rate:
        return Rate(self.tp, self.tp + self.fn)

    @property
    def false_negative_rate(self) -> Rate:
        """Positives the decision missed, out of all positives."""
        return Rate(self.fn, self.tp + self.fn)

    @property
    def false_positive_rate(self) -> Rate:
        """Negatives the decision flagged, out of all negatives."""
        return Rate(self.fp, self.fp + self.tn)

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn}


@dataclass
class ConfusionMatrix:
    """Counts of (gold label, predicted label). Gold labels are rows, predictions
    columns. Labels outside the fixed lists are kept and shown after them."""

    gold_labels: list[str]
    predicted_labels: list[str]
    counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def add(self, gold: str, predicted: str, n: int = 1) -> None:
        if gold not in self.gold_labels:
            self.gold_labels.append(gold)
        if predicted not in self.predicted_labels:
            self.predicted_labels.append(predicted)
        self.counts[(gold, predicted)] = self.counts.get((gold, predicted), 0) + n

    def merge(self, other: "ConfusionMatrix") -> None:
        for (gold, predicted), n in other.counts.items():
            self.add(gold, predicted, n)

    def count(self, gold: str, predicted: str) -> int:
        return self.counts.get((gold, predicted), 0)

    def row_total(self, gold: str) -> int:
        return sum(n for (g, _), n in self.counts.items() if g == gold)

    def column_total(self, predicted: str) -> int:
        return sum(n for (_, p), n in self.counts.items() if p == predicted)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def correct(self) -> int:
        return sum(n for (g, p), n in self.counts.items() if g == p)

    @property
    def accuracy(self) -> Rate:
        return Rate(self.correct, self.total)

    def precision(self, label: str) -> Rate:
        return Rate(self.count(label, label), self.column_total(label))

    def recall(self, label: str) -> Rate:
        return Rate(self.count(label, label), self.row_total(label))

    def rows(self) -> list[list[int]]:
        return [[self.count(g, p) for p in self.predicted_labels] for g in self.gold_labels]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gold_labels": list(self.gold_labels),
            "predicted_labels": list(self.predicted_labels),
            "rows": self.rows(),
        }


def mean_absolute_error(errors: Sequence[float]) -> float | None:
    return sum(abs(e) for e in errors) / len(errors) if errors else None
