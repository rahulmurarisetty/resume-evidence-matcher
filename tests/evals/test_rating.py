"""The human rating of evidence: the sheet a person fills in and its summary, on the
tiny labeled set in conftest.py."""

import csv
import json
from pathlib import Path

import pytest

from evals import rating_sheet, rating_summary
from evals.dataset import load_dataset
from evals.formats import FORMATS


def _sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_sheet_has_one_row_per_cited_line(
    tiny_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "sheet.csv"
    assert rating_sheet.main(["--data-dir", str(tiny_dataset), "--out", str(out)]) == 0
    assert "Fill in the rating column" in capsys.readouterr().out
    rows = _sheet(out)
    assert list(rows[0]) == list(rating_sheet.COLUMNS)
    assert {row["format"] for row in rows} == {"pdf_inline"}
    python = [row for row in rows if row["requirement"] == "Strong Python skills"]
    assert [row["evidence_line"] for row in python] == ["Built Python pipelines on Databricks."]
    assert python[0]["source"] == "exact" and python[0]["section"] == "experience"
    assert python[0]["page"] == "1" and python[0]["rank"] == "1"
    # A gap cites no line, so it has no row; every row starts unrated.
    assert not [row for row in rows if row["requirement"] == "Experience with Kafka"]
    assert all(row["rating"] == "" and row["rater_note"] == "" for row in rows)


def test_a_rated_sheet_is_never_overwritten(tiny_dataset: Path, tmp_path: Path) -> None:
    out = tmp_path / "sheet.csv"
    argv = ["--data-dir", str(tiny_dataset), "--out", str(out), "--format", "docx"]
    assert rating_sheet.main(argv) == 0
    rows = _sheet(out)
    rows[0]["rating"] = "supports"
    rating_sheet.write_sheet(rows, out)
    assert rating_sheet.main(argv) == 1
    assert _sheet(out)[0]["rating"] == "supports"
    assert rating_sheet.main([*argv, "--force"]) == 0
    assert _sheet(out)[0]["rating"] == ""


def test_default_sheet_path(tiny_dataset: Path) -> None:
    assert rating_sheet.default_path(rating_sheet.DATA_DIR) == (
        rating_sheet.RESULTS_DIR / "evidence_rating_sheet.csv"
    )
    assert rating_sheet.default_path(tiny_dataset).parent.name == "tiny_set"


def test_summary_of_a_filled_sheet(
    tiny_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = rating_sheet.sheet_rows(load_dataset(tiny_dataset), FORMATS[2])
    assert len(rows) >= 2
    filled = [dict(row) for row in rows]
    filled[0]["rating"] = "Supports"
    filled[1]["rating"] = " doesn't  support "
    out = tmp_path / "filled.csv"
    rating_sheet.write_sheet(filled, out)

    assert rating_summary.main([str(out), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["rows"], summary["rated"]) == (len(rows), 2)
    assert summary["unrated"] == len(rows) - 2
    assert summary["overall"]["supports"] == {"rate": 0.5, "count": 1, "total": 2}
    assert summary["overall"]["does not"] == {"rate": 0.5, "count": 1, "total": 2}
    assert summary["overall"]["supports_or_partly"]["count"] == 1
    assert set(summary["by_source"]) == {"exact"}

    assert rating_summary.main([str(out)]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(f"Rated 2 of {len(rows)} evidence lines.")
    assert "Supports the requirement: 50.0% (1/2)" in printed


def test_summary_of_an_empty_sheet_and_a_typo(
    tiny_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = rating_sheet.sheet_rows(load_dataset(tiny_dataset), FORMATS[0])
    out = tmp_path / "sheet.csv"
    rating_sheet.write_sheet(rows, out)
    assert rating_summary.main([str(out)]) == 0
    assert "No row is rated yet" in capsys.readouterr().out

    rows[0]["rating"] = "maybe"
    rating_sheet.write_sheet(rows, out)
    assert rating_summary.main([str(out)]) == 2
    assert "row 2: 'maybe'" in capsys.readouterr().out
    assert rating_summary.normalize_rating("Partial") == "partly"
    assert rating_summary.normalize_rating("does not") == "does not"
    assert rating_summary.normalize_rating("  ") is None
