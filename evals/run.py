"""Run the evaluation and write evals/results/latest.json and REPORT.md.

    python -m evals.run                    # default: exact matching, rule parser, all formats
    python -m evals.run --formats docx     # only the DOCX rendering
    python -m evals.run --semantic         # also matching by meaning (needs the ml extra)
    python -m evals.run --llm              # also Claude parsing and rewrites (needs a key)
    python -m evals.run --check            # exit 1 if a metric is past its threshold

The default run is deterministic: running it again on the same code writes the
same files, apart from the run date.
"""

import argparse
import json
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app import __version__, pipeline_version
from app.llm.client import LLMClient
from app.services.claude_jd_parser import ClaudeJobParser
from app.services.jd_parser import RuleJobParser
from app.services.semantic import Encoder, Reranker
from app.services.skills import get_catalog
from evals import errors, factcheck, pairs, requirements, resume_structure
from evals.dataset import Dataset, load_dataset
from evals.formats import FAMILIES, Format, select_formats
from evals.llm_mode import claude_from_env, run_rewrites
from evals.matching import FUZZY_THRESHOLD
from evals.pairs import ItemOutcome
from evals.pipeline import (
    CachedJobParser,
    Renderer,
    run_pairs,
    run_requirements,
    run_structure,
    score_pairs,
)
from evals.report import render_report
from evals.semantic_mode import HOW_TO_RUN, load_real_models, run_semantic
from evals.thresholds import check_thresholds, load_thresholds

EVALS_DIR = Path(__file__).resolve().parent
ROOT = EVALS_DIR.parent
RESULTS_DIR = EVALS_DIR / "results"
THRESHOLDS_PATH = EVALS_DIR / "thresholds.json"

LLM_HOW_TO_RUN = (
    "Put ANTHROPIC_API_KEY in the environment or in a local .env file (see the README), "
    "then run python -m evals.run --llm. It makes one parse call per job and up to "
    "LLM_MAX_SUGGESTIONS rewrite candidates per pair (20 by default)."
)


@dataclass(frozen=True)
class Options:
    families: tuple[str, ...] = FAMILIES
    semantic: bool = False
    llm: bool = False


@dataclass(frozen=True)
class LLMSetup:
    client: LLMClient
    parse_model: str
    rewrite_model: str
    budget: int


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _label_counts(dataset: Dataset) -> dict[str, int]:
    return {
        "resumes": len(dataset.resumes),
        "roles": sum(len(r.roles) for r in dataset.resumes.values()),
        "education_entries": sum(len(r.education) for r in dataset.resumes.values()),
        "jobs": len(dataset.jobs),
        "job_requirements": sum(len(j.requirements) for j in dataset.jobs.values()),
        "pairs": len(dataset.pairs),
        "pair_labels": sum(len(p.items) for p in dataset.pairs),
        "factcheck_development": len(dataset.factcheck_dev),
        "factcheck_holdout": len(dataset.factcheck_holdout),
    }


def _by_format(
    formats: Sequence[Format], rows: Sequence[Any], summarize: Any, attribute: str = "format"
) -> dict[str, Any]:
    return {
        "overall": summarize(rows),
        "by_format": {
            fmt.name: summarize([r for r in rows if getattr(r, attribute) == fmt.name])
            for fmt in formats
        },
    }


def _status_errors(items: Sequence[ItemOutcome]) -> list[dict[str, Any]]:
    """Wrong statuses. The same error in several formats is listed once, with its
    formats, and the evidence shown is from the first of them."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        if item.correct:
            continue
        key = (item.pair, item.text, item.app_status)
        if key in grouped:
            grouped[key]["formats"].append(item.format)
            continue
        entry = item.to_dict()
        del entry["format"]
        grouped[key] = {"formats": [item.format], **entry}
    return list(grouped.values())


def evaluate(
    dataset: Dataset,
    options: Options,
    *,
    run_date: date,
    semantic_models: tuple[Encoder, Reranker | None] | None = None,
    llm: LLMSetup | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """All metrics as one JSON-ready dict, plus the rewrite candidates when Claude ran.

    `semantic_models` and `llm` let tests pass fakes. Without them, --semantic loads
    the real models and --llm builds the Anthropic client from the environment, and
    each mode is skipped with a reason when that isn't possible.
    """
    catalog = get_catalog()
    formats = select_formats(options.families)
    format_names = [f.name for f in formats]
    renderer = Renderer(dataset)

    structure_results = run_structure(dataset, formats, renderer)
    rule_jobs, _ = run_requirements(dataset, RuleJobParser(), catalog)
    exact_runs = run_pairs(dataset, formats, renderer, catalog)
    exact_items = score_pairs(dataset, exact_runs, "exact")
    factcheck_sets = {
        "holdout": factcheck.evaluate_cases(dataset.factcheck_holdout, catalog),
        "development": factcheck.evaluate_cases(dataset.factcheck_dev, catalog),
    }

    metrics: dict[str, Any] = {
        "structure": _by_format(formats, structure_results, resume_structure.summarize),
        "requirements": {"rules": requirements.summarize(rule_jobs)},
        "pairs": {"exact": _by_format(formats, exact_items, pairs.summarize)},
        "factcheck": {
            name: {k: v for k, v in result.items() if k != "disagreements"}
            for name, result in factcheck_sets.items()
        },
    }
    details: dict[str, Any] = {
        "structure_per_resume": resume_structure.per_resume_rows(structure_results),
        "structure_failures": [
            item.to_dict()
            for result in structure_results
            for item in [
                *result.missed_roles,
                *result.date_errors,
                *result.missed_education,
                *result.education_errors,
            ]
        ],
        "extra_roles": [role for result in structure_results for role in result.extra_roles],
        "requirements_per_job": requirements.per_job_rows(rule_jobs),
        "requirement_failures": {
            "not_a_requirement": [s for job in rule_jobs for s in job.spurious],
            "not_extracted": [m for job in rule_jobs for m in job.missed],
            "priority_errors": [e for job in rule_jobs for e in job.priority_errors],
        },
        "pairs_per_pair": pairs.per_pair_rows(exact_items),
        "status_errors": _status_errors(exact_items),
        "factcheck_disagreements": {
            name: result["disagreements"] for name, result in factcheck_sets.items()
        },
    }

    # Matching by meaning.
    semantic_section: dict[str, Any] = {"status": "not requested", "how_to_run": HOW_TO_RUN}
    metrics["pairs"]["semantic"] = None
    if options.semantic:
        models = semantic_models if semantic_models is not None else load_real_models()
        if isinstance(models, str):
            semantic_section = {"status": "skipped", "reason": models, "how_to_run": HOW_TO_RUN}
        else:
            encoder, reranker = models
            semantic_items, extra = run_semantic(
                dataset, formats, renderer, catalog, encoder, reranker
            )
            metrics["pairs"]["semantic"] = _by_format(formats, semantic_items, pairs.summarize)
            semantic_section = {"status": "ran", **extra}
            details["semantic_status_errors"] = _status_errors(semantic_items)

    # Claude.
    llm_section: dict[str, Any] = {"status": "not requested", "how_to_run": LLM_HOW_TO_RUN}
    metrics["requirements"]["claude"] = None
    metrics["pairs"]["claude"] = None
    candidates: list[dict[str, Any]] | None = None
    if options.llm:
        setup = llm if llm is not None else _llm_from_env()
        if isinstance(setup, str):
            llm_section = {"status": "skipped", "reason": setup, "how_to_run": LLM_HOW_TO_RUN}
        else:
            parser = CachedJobParser(ClaudeJobParser(setup.client, setup.parse_model))
            claude_jobs, parsed = run_requirements(dataset, parser, catalog)
            metrics["requirements"]["claude"] = requirements.summarize(claude_jobs)
            claude_runs = run_pairs(dataset, formats, renderer, catalog, job_parser=parser)
            claude_items = score_pairs(dataset, claude_runs, "claude")
            metrics["pairs"]["claude"] = _by_format(formats, claude_items, pairs.summarize)
            first_format = [run for run in claude_runs if run.format == formats[0].name]
            rewrite_summary, candidates = run_rewrites(
                first_format,
                setup.client,
                model=setup.rewrite_model,
                budget=setup.budget,
                catalog=catalog,
            )
            llm_section = {
                "status": "ran",
                "parse_model": setup.parse_model,
                "rewrite_model": setup.rewrite_model,
                "parsers_used": {job.job: job.parser for job in claude_jobs},
                "dropped_requirements": {
                    name: p.parser.dropped_requirements for name, p in parsed.items()
                },
                "rewrite_format": formats[0].name,
                "rewrites": rewrite_summary,
            }

    git_commit = _git("rev-parse", "--short", "HEAD")
    git_status = _git("status", "--porcelain")
    results: dict[str, Any] = {
        "meta": {
            "date": run_date.isoformat(),
            "git_commit": git_commit,
            "uncommitted_changes": bool(git_status) if git_status is not None else None,
            "app_version": __version__,
            "pipeline_version": pipeline_version(semantic=False),
            "as_of": dataset.as_of.isoformat(),
            "formats": [{"name": f.name, "description": f.description} for f in formats],
            "modes": {
                "exact": "ran",
                "semantic": semantic_section["status"],
                "llm": llm_section["status"],
            },
            "job_parser": "rules",
            "fuzzy_threshold": FUZZY_THRESHOLD,
            "years_tolerance": resume_structure.YEARS_TOLERANCE,
            "python": platform.python_version(),
            "pymupdf": _package_version("pymupdf"),
            "python_docx": _package_version("python-docx"),
            "labels": _label_counts(dataset),
        },
        "metrics": metrics,
        "semantic": semantic_section,
        "llm": llm_section,
        "error_analysis": errors.find_patterns(
            structure=structure_results,
            requirements=rule_jobs,
            items=exact_items,
            factcheck=factcheck_sets,
            formats=format_names,
        ),
        "details": details,
    }
    return results, candidates


def _llm_from_env() -> LLMSetup | str:
    found = claude_from_env()
    if isinstance(found, str):
        return found
    client, settings = found
    return LLMSetup(
        client=client,
        parse_model=settings.llm_parse_model,
        rewrite_model=settings.llm_rewrite_model,
        budget=settings.llm_max_suggestions,
    )


def write_outputs(
    results: dict[str, Any], candidates: list[dict[str, Any]] | None, out_dir: Path
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / "latest.json", out_dir / "REPORT.md"]
    written[0].write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written[1].write_text(render_report(results), encoding="utf-8")
    if candidates is not None:
        path = out_dir / "llm_candidates.json"
        path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False) + "\n", "utf-8")
        written.append(path)
    return written


def _families(value: str) -> tuple[str, ...]:
    families = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part))
    try:
        select_formats(families)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not families:
        raise argparse.ArgumentTypeError("name at least one format")
    return families


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Measure the app against the hand-labeled evaluation set in evals/data/.",
    )
    parser.add_argument(
        "--formats",
        type=_families,
        default=FAMILIES,
        help="comma-separated: pdf (both PDF layouts), docx. Default: pdf,docx",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="also score the pairs with matching by meaning (needs sentence-transformers)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="also use the Claude parser and generate rewrites (needs ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--out", type=Path, default=RESULTS_DIR, help="output folder (default evals/results)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with status 1 if a metric is past its threshold in evals/thresholds.json",
    )
    return parser.parse_args(argv)


def _headline(results: dict[str, Any]) -> list[str]:
    m = results["metrics"]
    lines = [
        ("Role recall", m["structure"]["overall"]["role_recall"]),
        ("Requirement extraction recall", m["requirements"]["rules"]["extraction_recall"]),
        ("Requirement extraction precision", m["requirements"]["rules"]["extraction_precision"]),
        ("Pair status accuracy", m["pairs"]["exact"]["overall"]["status_accuracy"]),
        ("False proven rate", m["pairs"]["exact"]["overall"]["false_proven_rate"]),
        ("Evidence recall@3", m["pairs"]["exact"]["overall"]["evidence_recall_at_3"]),
        ("Fact checker false passes (holdout)", m["factcheck"]["holdout"]["false_pass_rate"]),
    ]
    return [f"  {name}: {_rate_text(value)}" for name, value in lines]


def _rate_text(value: dict[str, Any]) -> str:
    rate = value["rate"]
    shown = "n/a" if rate is None else f"{rate * 100:.1f}%"
    return f"{shown} ({value['count']}/{value['total']})"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    options = Options(families=args.formats, semantic=args.semantic, llm=args.llm)
    results, candidates = evaluate(load_dataset(), options, run_date=date.today())
    written = write_outputs(results, candidates, args.out)

    print("Evaluation finished (exact matching, rule parser).")
    print("\n".join(_headline(results)))
    for mode in ("semantic", "llm"):
        section = results[mode]
        if section["status"] == "skipped":
            print(f"{mode}: skipped, {section['reason']} {section['how_to_run']}")
    for path in written:
        print(f"wrote {path}")

    if not args.check:
        return 0
    if options.families != FAMILIES:
        print("note: the thresholds were set on the default run with every format.")
    failures = check_thresholds(results["metrics"], load_thresholds(THRESHOLDS_PATH))
    if failures:
        print(f"check failed: {len(failures)} metric(s) past their thresholds")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("check passed: every metric is within its threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
