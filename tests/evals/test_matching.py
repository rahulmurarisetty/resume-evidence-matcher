"""Text normalization, fuzzy thresholds, one-to-one alignment and evidence hits."""

import pytest

from evals.matching import (
    FUZZY_THRESHOLD,
    MatchKind,
    align,
    align_texts,
    all_fields_score,
    evidence_hit,
    field_score,
    normalize_space,
    normalize_text,
    ratio,
    text_match,
)


def test_normalize_text_drops_case_punctuation_and_extra_space() -> None:
    assert normalize_text("  Strong C#,  ASP.NET   Core skills! ") == "strong c asp net core skills"
    assert normalize_text("Mar 2022 \u2013 Present") == normalize_text("Mar 2022 - Present")
    assert normalize_text(None) == ""


def test_normalize_space_keeps_case_and_punctuation() -> None:
    assert normalize_space(" Built  ETL\u00a0pipelines. ") == "Built ETL pipelines."


def test_ratio_matches_hand_computed_values() -> None:
    # 2 * matching characters / total characters
    assert ratio("abcdefghij", "abcdefghix") == pytest.approx(0.9)
    assert ratio("abcdefghij", "abcdefgxyz") == pytest.approx(0.7)


def test_text_match_kinds() -> None:
    exact = text_match("Experience with dbt.", "experience with  DBT")
    assert exact is not None and exact.kind is MatchKind.EXACT and exact.ratio == 1.0

    contained = text_match("Experience with dbt", "Experience with dbt is a plus")
    assert contained is not None and contained.kind is MatchKind.CONTAINS

    fuzzy = text_match("abcdefghij", "abcdefghix")
    assert fuzzy is not None and fuzzy.kind is MatchKind.FUZZY

    assert text_match("abcdefghij", "abcdefgxyz") is None
    assert text_match("", "anything") is None


def test_fuzzy_threshold_is_inclusive() -> None:
    # ratio 0.85 exactly: 17 of 20 characters shared in both strings
    a, b = "abcdefghijklmnopqrst", "abcdefghijklmnopqxyz"
    assert ratio(a, b) == pytest.approx(FUZZY_THRESHOLD)
    assert text_match(a, b) is not None
    assert field_score(a, b) == pytest.approx(0.85)
    assert text_match(a, b, threshold=0.86) is None
    assert field_score(a, b, threshold=0.86) is None


def test_field_score() -> None:
    assert field_score("Example Mutual", "example mutual") == 1.0
    assert field_score(None, None) == 1.0
    assert field_score(None, "Example Mutual") is None
    assert field_score("Example Mutual, Jacksonville, FL", "Example Mutual") is None
    assert field_score("Sr. Data Engineer", "Senior Data Engineer") == pytest.approx(16 / 18)


def test_all_fields_score_needs_every_field() -> None:
    assert all_fields_score([("Data Engineer", "Data Engineer"), ("Acme", "Acme")]) == 1.0
    assert all_fields_score([("Data Engineer", "Data Engineer"), ("Acme", "Other Co")]) is None
    assert all_fields_score([]) is None


def test_align_is_one_to_one_and_prefers_the_best_pair() -> None:
    predicted = ["Python and SQL", "Experience with dbt", "What we offer"]
    gold = ["Experience with dbt", "Strong Python and SQL skills"]
    alignment = align_texts(predicted, gold)
    assert alignment.gold_to_predicted() == {0: 1, 1: 0}
    assert alignment.unmatched_predicted == (2,)
    assert alignment.unmatched_gold == ()


def test_align_never_reuses_a_prediction() -> None:
    # Both labels contain the prediction; only the better one gets it.
    alignment = align_texts(["Python"], ["Python", "Strong Python skills"])
    assert alignment.gold_to_predicted() == {0: 0}
    assert alignment.unmatched_gold == (1,)


def test_align_breaks_ties_by_list_order() -> None:
    alignment = align(["a", "a"], ["a", "a"], lambda p, g: 1.0)
    assert [(p, g) for p, g, _ in alignment.matched] == [(0, 0), (1, 1)]


@pytest.mark.parametrize(
    ("lines", "k", "expected"),
    [
        (["Built PySpark pipelines on Databricks that ingest claims."], 1, True),
        (["Languages: Python, SQL", "Built PySpark pipelines on Databricks."], 1, False),
        (["Languages: Python, SQL", "Built PySpark pipelines on Databricks."], 3, True),
        (["Built   PySpark\npipelines on Databricks"], 1, True),
        ([], 3, False),
    ],
)
def test_evidence_hit(lines: list[str], k: int, expected: bool) -> None:
    assert evidence_hit(lines, ["Built PySpark pipelines on Databricks"], k) is expected


def test_evidence_hit_accepts_a_line_inside_the_label() -> None:
    gold = ["Fixed WCAG 2.1 AA issues found in an accessibility audit, closing 120 tickets."]
    assert evidence_hit(["Fixed WCAG 2.1 AA issues"], gold, 1)
    assert not evidence_hit(["Fixed WCAG"], ["Something else"], 1)
