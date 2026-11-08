"""Write a sheet for a person to rate whether each cited evidence line supports its
requirement.

    python -m evals.rating_sheet                      # the development set
    python -m evals.rating_sheet --data-dir DIR       # another labeled set
    python -m evals.rating_sheet --format docx --out path/to/sheet.csv

The sheet has one row per pair, requirement and evidence line the app's report
cites for it (exact evidence skill by skill, then related evidence), read from one
format (pdf_inline by default, so each line appears once). A person fills in the
"rating" column with one of: supports, partly, does not. Then
`python -m evals.rating_summary <sheet>` computes the human-rated share.

An existing sheet with ratings in it is never overwritten unless --force is given,
so a person's work isn't lost by running this again.
"""

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from app.models import RequirementMatch
from app.services.skills import get_catalog
from evals.dataset import DATA_DIR, Dataset, dataset_name, load_dataset
from evals.formats import FORMATS, Format
from evals.pipeline import Renderer, run_pairs

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SHEET_NAME = "evidence_rating_sheet.csv"
COLUMNS = (
    "pair",
    "format",
    "requirement_id",
    "priority",
    "requirement",
    "app_status",
    "rank",
    "source",
    "section",
    "page",
    "evidence_line",
    "matched",
    "rating",
    "rater_note",
)
RATINGS = ("supports", "partly", "does not")


def evidence_rows(match: RequirementMatch) -> list[dict[str, str]]:
    """The lines the report cites for one requirement, in the report's order, each
    once."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for skill in match.skills:
        for evidence in skill.evidence:
            if evidence.span_id in seen:
                continue
            seen.add(evidence.span_id)
            rows.append(
                {
                    "source": "exact",
                    "section": evidence.section.value,
                    "page": "" if evidence.page is None else str(evidence.page),
                    "evidence_line": evidence.text,
                    "matched": f"{skill.skill} via {evidence.matched_term!r}",
                }
            )
    for related in match.related_evidence:
        if related.span_id in seen:
            continue
        seen.add(related.span_id)
        rows.append(
            {
                "source": "related",
                "section": related.section.value,
                "page": "" if related.page is None else str(related.page),
                "evidence_line": related.text,
                "matched": f"score {related.score}",
            }
        )
    return rows


def sheet_rows(dataset: Dataset, fmt: Format) -> list[dict[str, str]]:
    runs = run_pairs(dataset, [fmt], Renderer(dataset), get_catalog())
    rows: list[dict[str, str]] = []
    for run in runs:
        for match in run.report.matches:
            for rank, line in enumerate(evidence_rows(match), start=1):
                rows.append(
                    {
                        "pair": run.pair.key,
                        "format": fmt.name,
                        "requirement_id": match.requirement.id,
                        "priority": match.requirement.priority.value,
                        "requirement": match.requirement.text,
                        "app_status": match.status.value,
                        "rank": str(rank),
                        **line,
                        "rating": "",
                        "rater_note": "",
                    }
                )
    return rows


def has_ratings(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8", newline="") as handle:
        return any((row.get("rating") or "").strip() for row in csv.DictReader(handle))


def write_sheet(rows: Sequence[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def default_path(data_dir: Path) -> Path:
    name = dataset_name(data_dir)
    folder = RESULTS_DIR if name == "development" else RESULTS_DIR / name
    return folder / SHEET_NAME


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.rating_sheet",
        description="Write a CSV sheet for a person to rate each cited evidence line.",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--format",
        choices=[f.name for f in FORMATS],
        default=FORMATS[0].name,
        help="the rendering to read (default pdf_inline)",
    )
    parser.add_argument("--out", type=Path, default=None, help="where to write the sheet")
    parser.add_argument(
        "--force", action="store_true", help="overwrite a sheet that already has ratings"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    path = args.out or default_path(args.data_dir)
    if has_ratings(path) and not args.force:
        print(f"{path} already has ratings in it, so it wasn't overwritten. Use --force.")
        return 1
    fmt = next(f for f in FORMATS if f.name == args.format)
    rows = sheet_rows(load_dataset(args.data_dir), fmt)
    write_sheet(rows, path)
    pairs = len({row["pair"] for row in rows})
    print(
        f"wrote {path}: {len(rows)} evidence lines across {pairs} pairs. Fill in the rating "
        f"column with one of: {', '.join(RATINGS)}. Then run python -m evals.rating_summary "
        f"{path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
