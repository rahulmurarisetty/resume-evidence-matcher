"""Rates, binary counts, confusion matrices and threshold checks on tiny inputs."""

import json
from pathlib import Path

import pytest

from evals.metrics import BinaryCounts, ConfusionMatrix, Rate, mean_absolute_error, pooled, rate_of
from evals.thresholds import Thresholds, check_thresholds, load_thresholds, lookup


def test_rate_value_text_and_dict() -> None:
    rate = Rate(3, 4)
    assert rate.value == 0.75
    assert str(rate) == "75.0% (3/4)"
    assert rate.to_dict() == {"rate": 0.75, "count": 3, "total": 4}
    assert Rate(0, 0).value is None
    assert str(Rate(0, 0)) == "n/a (0/0)"
    assert Rate(2, 3).to_dict()["rate"] == 0.6667


def test_rates_pool_by_counts_not_by_averaging() -> None:
    assert pooled([Rate(1, 1), Rate(1, 3)]) == Rate(2, 4)
    assert rate_of([True, False, True]) == Rate(2, 3)


def test_binary_counts_precision_recall_and_error_rates() -> None:
    # (gold positive, predicted positive)
    counts = BinaryCounts.from_pairs(
        [(True, True), (True, True), (True, False), (False, True), (False, False), (False, False)]
    )
    assert counts.to_dict() == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}
    assert counts.accuracy == Rate(4, 6)
    assert counts.precision == Rate(2, 3)
    assert counts.recall == Rate(2, 3)
    assert counts.false_negative_rate == Rate(1, 3)
    assert counts.false_positive_rate == Rate(1, 3)


def test_binary_counts_with_no_positives() -> None:
    counts = BinaryCounts.from_pairs([(False, False)])
    assert counts.precision.value is None
    assert counts.recall.value is None
    assert counts.accuracy == Rate(1, 1)


def test_confusion_matrix_counts_rows_and_columns() -> None:
    matrix = ConfusionMatrix(["direct", "gap"], ["direct", "gap", "not_extracted"])
    for gold, predicted in [
        ("direct", "direct"),
        ("direct", "direct"),
        ("direct", "gap"),
        ("gap", "gap"),
        ("gap", "direct"),
        ("gap", "not_extracted"),
    ]:
        matrix.add(gold, predicted)
    assert matrix.rows() == [[2, 1, 0], [1, 1, 1]]
    assert matrix.accuracy == Rate(3, 6)
    assert matrix.precision("direct") == Rate(2, 3)
    assert matrix.recall("direct") == Rate(2, 3)
    assert matrix.precision("gap") == Rate(1, 2)
    assert matrix.recall("gap") == Rate(1, 3)
    assert matrix.to_dict()["predicted_labels"] == ["direct", "gap", "not_extracted"]


def test_confusion_matrix_keeps_unexpected_labels_and_merges() -> None:
    first = ConfusionMatrix(["a"], ["a"])
    first.add("a", "b")
    second = ConfusionMatrix(["a"], ["a"])
    second.add("a", "a", 2)
    first.merge(second)
    assert first.predicted_labels == ["a", "b"]
    assert first.rows() == [[2, 1]]
    assert first.total == 3


def test_mean_absolute_error() -> None:
    assert mean_absolute_error([0.5, -1.5]) == 1.0
    assert mean_absolute_error([]) is None


METRICS = {
    "pairs": {"overall": {"status_accuracy": {"rate": 0.7, "count": 7, "total": 10}}},
    "structure": {"overall": {"total_years_mae": 0.9, "flag": True}},
}


def test_lookup_reads_rates_and_numbers() -> None:
    assert lookup(METRICS, "pairs.overall.status_accuracy") == 0.7
    assert lookup(METRICS, "structure.overall.total_years_mae") == 0.9
    assert lookup(METRICS, "structure.overall.flag") is None
    assert lookup(METRICS, "pairs.overall.missing") is None
    assert lookup(METRICS, "pairs.overall.status_accuracy.rate.deeper") is None


def test_check_thresholds_reports_each_failure() -> None:
    thresholds = Thresholds(
        floors={"pairs.overall.status_accuracy": 0.8, "pairs.overall.nothing": 0.1},
        ceilings={"structure.overall.total_years_mae": 0.5},
    )
    failures = check_thresholds(METRICS, thresholds)
    assert len(failures) == 3
    assert "below the floor 0.8" in failures[0]
    assert "not measured" in failures[1]
    assert "above the ceiling 0.5" in failures[2]


def test_check_thresholds_passes_at_the_boundary() -> None:
    thresholds = Thresholds(
        floors={"pairs.overall.status_accuracy": 0.7},
        ceilings={"structure.overall.total_years_mae": 0.9},
    )
    assert check_thresholds(METRICS, thresholds) == []


def test_load_thresholds_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"_comment": ["x"], "floors": {"a.b": 0.5}}), encoding="utf-8")
    loaded = load_thresholds(path)
    assert loaded.floors == {"a.b": 0.5}
    assert loaded.ceilings == {}


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_rate_bounds(value: float) -> None:
    assert Rate(int(value), 1).value == value
