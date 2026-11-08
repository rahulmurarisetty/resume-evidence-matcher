"""Summarize a filled-in evidence rating sheet.

    python -m evals.rating_summary evals/results/evidence_rating_sheet.csv
    python -m evals.rating_summary sheet.csv --json

Counts the rows a person rated, and the share of them rated "supports", "partly"
and "does not", overall, by the app's status and by the kind of evidence (exact or
related by meaning). Rows with an empty rating are left out of the shares and
counted as unrated. A rating that isn't one of the three is an error, with its row
number, so a typo never counts as anything.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from evals.metrics import Rate
from evals.rating_sheet import RATINGS

_ALIASES = {
    "supports": "supports",
    "support": "supports",
    "partly": "partly",
    "partial": "partly",
    "partially": "partly",
    "does not": "does not",
    "does not support": "does not",
    "doesn't": "does not",
    "doesn't support": "does not",
}


class RatingError(ValueError):
    pass


def normalize_rating(value: str) -> str | None:
    """The rating in its standard form, None when empty. Raises on anything else."""
    text = " ".join(value.strip().lower().replace("\u2019", "'").split())
    if not text:
        return None
    if text not in _ALIASES:
        raise RatingError(text)
    return _ALIASES[text]


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _shares(ratings: Iterable[str]) -> dict[str, Any]:
    counts = Counter(ratings)
    rated = sum(counts.values())
    shares: dict[str, Any] = {rating: Rate(counts[rating], rated).to_dict() for rating in RATINGS}
    shares["supports_or_partly"] = Rate(counts["supports"] + counts["partly"], rated).to_dict()
    return shares


def summarize(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    bad: list[str] = []
    rated: list[tuple[dict[str, str], str]] = []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            rating = normalize_rating(row.get("rating") or "")
        except RatingError as exc:
            bad.append(f"row {number}: {exc.args[0]!r}")
            continue
        if rating is not None:
            rated.append((row, rating))
    if bad:
        raise RatingError(
            f"ratings must be one of {', '.join(RATINGS)} (or empty): " + "; ".join(bad)
        )
    by_status: dict[str, list[str]] = {}
    by_source: dict[str, list[str]] = {}
    for row, rating in rated:
        by_status.setdefault(row.get("app_status", ""), []).append(rating)
        by_source.setdefault(row.get("source", ""), []).append(rating)
    return {
        "rows": len(rows),
        "rated": len(rated),
        "unrated": len(rows) - len(rated),
        "overall": _shares(r for _, r in rated),
        "by_app_status": {k: _shares(v) for k, v in sorted(by_status.items())},
        "by_source": {k: _shares(v) for k, v in sorted(by_source.items())},
    }


def _rate_text(value: dict[str, Any]) -> str:
    rate = value["rate"]
    shown = "n/a" if rate is None else f"{rate * 100:.1f}%"
    return f"{shown} ({value['count']}/{value['total']})"


def render(summary: dict[str, Any]) -> str:
    lines = [f"Rated {summary['rated']} of {summary['rows']} evidence lines."]
    if not summary["rated"]:
        lines.append("No row is rated yet, so there is no human-rated share to report.")
        return "\n".join(lines) + "\n"
    overall = summary["overall"]
    lines += [
        f"Supports the requirement: {_rate_text(overall['supports'])}",
        f"Partly supports it: {_rate_text(overall['partly'])}",
        f"Does not support it: {_rate_text(overall['does not'])}",
        f"Supports or partly: {_rate_text(overall['supports_or_partly'])}",
    ]
    for title, key in (("By the app's status", "by_app_status"), ("By kind", "by_source")):
        lines.append(f"{title}:")
        for name, shares in summary[key].items():
            lines.append(f"  {name}: supports {_rate_text(shares['supports'])}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.rating_summary",
        description="Summarize a filled-in evidence rating sheet.",
    )
    parser.add_argument("sheet", type=Path)
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    try:
        summary = summarize(read_sheet(args.sheet))
    except RatingError as exc:
        print(f"error: {exc}")
        return 2
    print(json.dumps(summary, indent=2) if args.json else render(summary), end="")
    if args.json:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
