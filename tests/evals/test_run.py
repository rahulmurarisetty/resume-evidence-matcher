"""Smoke tests for the evaluation run on a small subset of the labeled set.

No test loads a real model or calls Claude: matching by meaning uses the fake
encoder and reranker, and the Claude path uses the scripted fake client.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.llm.client import DEFAULT_PARSE_MODEL, DEFAULT_REWRITE_MODEL
from app.services.claude_jd_parser import ClaudeJobOutput
from app.services.rewrite import RewriteOutput
from evals import run
from evals.dataset import Dataset, load_dataset
from evals.report import render_report
from evals.thresholds import load_thresholds, lookup
from tests.fakes import FakeEncoder, FakeLLMClient, FakeReranker, LLMCall

RUN_DATE = date(2026, 11, 8)


@pytest.fixture(scope="module")
def subset() -> Dataset:
    # The first two pairs: r01 and r11 against j01.
    return load_dataset().limited(2)


@pytest.fixture(scope="module")
def default_results(subset: Dataset) -> dict[str, object]:
    results, candidates = run.evaluate(subset, run.Options(), run_date=RUN_DATE)
    assert candidates is None
    return results


def test_dataset_loads_every_label() -> None:
    dataset = load_dataset()
    assert len(dataset.resumes) == 12
    assert len(dataset.jobs) == 8
    assert sum(len(p.items) for p in dataset.pairs) == 176
    assert len(dataset.factcheck_dev) == 60
    assert len(dataset.factcheck_holdout) == 40
    assert dataset.as_of == date(2026, 11, 1)


def test_default_run_on_a_subset(subset: Dataset, default_results: dict[str, object]) -> None:
    results = default_results
    meta = results["meta"]
    assert isinstance(meta, dict)
    assert meta["modes"] == {"exact": "ran", "semantic": "not requested", "llm": "not requested"}
    assert meta["pipeline_version"].endswith("-exact")
    assert meta["as_of"] == "2026-11-01"
    assert [f["name"] for f in meta["formats"]] == ["pdf_inline", "pdf_separate", "docx"]

    metrics = results["metrics"]
    assert isinstance(metrics, dict)
    pair_items = sum(len(p.items) for p in subset.pairs)
    overall = metrics["pairs"]["exact"]["overall"]
    assert overall["items"] == 3 * pair_items
    assert sum(sum(row) for row in overall["confusion"]["rows"]) == 3 * pair_items
    for name in ("pdf_inline", "pdf_separate", "docx"):
        assert metrics["pairs"]["exact"]["by_format"][name]["items"] == pair_items
    # r01 and r11 are read cleanly in every format.
    assert metrics["structure"]["overall"]["role_recall"]["rate"] == 1.0
    assert metrics["structure"]["overall"]["total_years_within_half"]["rate"] == 1.0
    assert metrics["requirements"]["rules"]["jobs"] == 1
    assert metrics["factcheck"]["holdout"]["cases"] == 40
    assert metrics["pairs"]["semantic"] is None
    assert metrics["pairs"]["claude"] is None
    # v1.0: the Word export is read back the same, and is a plain file.
    quality = metrics["document_quality"]["overall"]
    assert (quality["files"], quality["pairs"]) == (6, 6)
    assert quality["round_trip_unchanged"] == {"rate": 1.0, "count": 6, "total": 6}
    assert quality["structure_ok"]["rate"] == 1.0
    assert set(quality["structure_checks"]) >= {"no_tables", "one_column", "language"}
    # Everything is JSON-ready.
    json.dumps(results)


def test_default_run_is_deterministic(subset: Dataset, default_results: dict[str, object]) -> None:
    again, _ = run.evaluate(subset, run.Options(), run_date=RUN_DATE)
    assert json.dumps(again, sort_keys=True) == json.dumps(default_results, sort_keys=True)


def test_report_has_every_section_and_follows_the_prose_rules(
    default_results: dict[str, object],
) -> None:
    report = render_report(default_results)
    for heading in (
        # v0.5: the title names the dataset.
        "# Evaluation report: development set",
        "## Headline numbers",
        "## Before and after, development set (used to find and fix these failures, so these "
        "numbers are optimistic)",
        "## Resume structure",
        "## Requirement extraction",
        "## Evidence and status per pair",
        "## Document quality",
        "## Fact checker",
        "## Matching by meaning",
        "## Claude parser and rewrites",
        "## Error analysis",
        "## Known weaknesses of this evaluation",
    ):
        assert f"\n{heading}\n" in f"\n{report}"
    assert "development set" in report.lower() and "optimistic" in report
    assert "Run date: 2026-11-08" in report
    assert "\u2014" not in report  # no em dashes
    assert "**" not in report
    assert not re.search(r"[\u201c\u201d\u2018\u2019]", report)


def test_thresholds_file_paths_all_resolve(default_results: dict[str, object]) -> None:
    thresholds = load_thresholds(run.THRESHOLDS_PATH)
    assert thresholds.floors and thresholds.ceilings
    assert "factcheck.holdout.false_pass_rate" in thresholds.ceilings
    metrics = default_results["metrics"]
    assert isinstance(metrics, dict)
    for path in [*thresholds.floors, *thresholds.ceilings]:
        # The subset has no gap labels, so some rates are 0/0 here; the path must exist.
        node: object = metrics
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, path
            node = node[part]
        assert isinstance(node, dict) and "rate" in node, path
    assert lookup(metrics, "pairs.exact.overall.status_accuracy") is not None


def test_cli_writes_outputs_and_check_fails_past_a_threshold(
    subset: Dataset,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # v0.5: main passes --data-dir to load_dataset.
    monkeypatch.setattr(run, "load_dataset", lambda data_dir: subset)
    out = tmp_path / "results"
    assert run.main(["--formats", "docx", "--out", str(out)]) == 0
    assert (out / "latest.json").is_file() and (out / "REPORT.md").is_file()
    assert not (out / "llm_candidates.json").exists()
    written = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in written["meta"]["formats"]] == ["docx"]

    strict = tmp_path / "thresholds.json"
    strict.write_text(
        json.dumps({"floors": {"pairs.exact.overall.status_accuracy": 1.01}}), encoding="utf-8"
    )
    monkeypatch.setattr(run, "THRESHOLDS_PATH", strict)
    assert run.main(["--formats", "docx", "--out", str(out), "--check"]) == 1
    printed = capsys.readouterr().out
    assert "check failed" in printed and "status_accuracy" in printed

    lenient = tmp_path / "lenient.json"
    lenient.write_text(
        json.dumps({"ceilings": {"pairs.exact.overall.overclaim_rate": 1.0}}), encoding="utf-8"
    )
    monkeypatch.setattr(run, "THRESHOLDS_PATH", lenient)
    assert run.main(["--formats", "docx", "--out", str(out), "--check"]) == 0
    assert "check passed" in capsys.readouterr().out


def test_cli_rejects_an_unknown_format(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        run.parse_args(["--formats", "pdf,odt"])
    assert "unknown format odt" in capsys.readouterr().err
    assert run.parse_args(["--formats", "docx,pdf"]).formats == ("docx", "pdf")


def test_semantic_mode_skips_with_a_reason_when_models_are_missing(
    subset: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "load_real_models", lambda: "sentence-transformers isn't installed.")
    results, _ = run.evaluate(
        subset.limited(1), run.Options(families=("docx",), semantic=True), run_date=RUN_DATE
    )
    assert results["semantic"]["status"] == "skipped"
    assert results["metrics"]["pairs"]["semantic"] is None
    report = render_report(results)
    assert "--semantic was given, but sentence-transformers isn't installed." in report
    assert 'pip install -e ".[dev,ml]"' in report


def test_semantic_mode_with_fake_models(subset: Dataset) -> None:
    results, _ = run.evaluate(
        subset,
        run.Options(families=("docx",), semantic=True),
        run_date=RUN_DATE,
        semantic_models=(FakeEncoder(), FakeReranker()),
    )
    section = results["semantic"]
    assert section["status"] == "ran"
    assert section["reports_without_semantic"] == 0
    assert (section["embedding_model"], section["rerank_model"]) == ("FakeEncoder", "FakeReranker")
    assert [row["threshold"] for row in section["threshold_sweep"]] == [0.3, 0.4, 0.5, 0.6, 0.7]
    semantic = results["metrics"]["pairs"]["semantic"]["overall"]
    assert semantic["items"] == results["metrics"]["pairs"]["exact"]["overall"]["items"]
    # Matching by meaning can only add adjacent results; it never proves a gap.
    assert semantic["false_proven_rate"]["count"] == 0
    report = render_report(results)
    assert "| Threshold | Status accuracy |" in report
    assert "| Metric | exact, rules | semantic |" in report


def test_llm_mode_skips_without_a_key(
    subset: Dataset, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env file here, and conftest removed any key
    results, candidates = run.evaluate(
        subset.limited(1), run.Options(families=("docx",), llm=True), run_date=RUN_DATE
    )
    assert candidates is None
    assert results["llm"]["status"] == "skipped"
    assert results["llm"]["reason"] == "ANTHROPIC_API_KEY isn't set."
    report = render_report(results)
    assert "No call was made to a model provider." in report
    # v1.0: the report says how the owner runs it with his own key, and what it measures.
    assert "To run it with your own key, put ANTHROPIC_API_KEY" in report
    assert "this section measures the hallucination rate of generated suggestions" in report


def _fake_claude(dataset: Dataset) -> FakeLLMClient:
    """Parses each job into its labeled lines and suggests two rewrites per bullet:
    a trimmed copy, which passes the fact checker, and one that adds an employer."""
    by_text = {job.text: job for job in dataset.jobs.values()}

    def handler(call: LLMCall) -> object:
        if call.output_type is ClaudeJobOutput:
            raw = call.user.split("<job_description>\n", 1)[1].rsplit("\n</job_description>", 1)[0]
            job = by_text[raw]
            return {
                "title": job.title,
                "requirements": [
                    {"text": r.text, "priority": r.priority} for r in job.requirements
                ],
            }
        assert call.output_type is RewriteOutput
        bullet = call.user.split("<bullet>\n", 1)[1].split("\n</bullet>", 1)[0]
        trimmed = " ".join(bullet.rstrip(".").split()[:6]) + "."
        return {"rewrites": [trimmed, f"{bullet.rstrip('.')} at Amazon."]}

    return FakeLLMClient(handler=handler)


def test_llm_mode_with_a_fake_client(subset: Dataset, tmp_path: Path) -> None:
    client = _fake_claude(subset)
    setup = run.LLMSetup(client, DEFAULT_PARSE_MODEL, DEFAULT_REWRITE_MODEL, budget=4)
    results, candidates = run.evaluate(
        subset, run.Options(families=("docx",), llm=True), run_date=RUN_DATE, llm=setup
    )
    section = results["llm"]
    assert section["status"] == "ran"
    assert section["parsers_used"] == {"j01_senior_data_engineer": "claude"}
    claude = results["metrics"]["requirements"]["claude"]
    assert claude["extraction_recall"]["rate"] == 1.0
    assert claude["extraction_precision"]["rate"] == 1.0
    assert results["metrics"]["pairs"]["claude"]["overall"]["items"] == 22

    rewrites = section["rewrites"]
    assert rewrites["pairs"] == 2
    assert rewrites["calls"] == 4  # two calls per pair use the budget of 4 candidates
    assert rewrites["candidates"] == 8
    assert rewrites["rejected"] >= 4  # every "at Amazon" candidate
    assert rewrites["rejections_by_kind"]["name"] >= 4
    assert rewrites["matches_app_counts"] is True
    assert rewrites["skipped"].get("limit_reached", 0) > 0
    assert [row["candidates"] for row in rewrites["per_pair"]] == [4, 4]
    assert sum(row["rejected"] for row in rewrites["per_pair"]) == rewrites["rejected"]
    # One parse call per job however many pairs and formats use it.
    parse_calls = [c for c in client.calls if c.output_type is ClaudeJobOutput]
    assert len(parse_calls) == 1

    assert candidates is not None and len(candidates) == 8
    # v1.0: every candidate waits for a person's review.
    assert all(c["manual_review"] is None for c in candidates)
    amazon = [c for c in candidates if c["candidate"].endswith("at Amazon.")]
    assert all(c["verdict"] == "rejected" and c["reasons"] for c in amazon)
    written = run.write_outputs(results, candidates, tmp_path)
    assert tmp_path / "llm_candidates.json" in written
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "Rejected by the fact checker" in report
    assert "| Hallucination rate caught by the fact checker (rejected of checked) |" in report
    assert "empty manual_review field" in report
    assert (
        "| Pair | Bullets chosen | Candidates | Kept | Rejected | Rejected for | Unchanged |"
        in report
    )


# ---------------------------------------------------------------------------
# --data-dir: another labeled set with the same layout
# ---------------------------------------------------------------------------


def test_another_data_dir_loads_without_fact_check_labels(tiny_dataset: Path) -> None:
    dataset = load_dataset(tiny_dataset)
    assert dataset.name == "tiny_set"
    assert not dataset.is_development
    assert not dataset.has_factcheck
    assert dataset.source == tiny_dataset.resolve().as_posix()
    assert (len(dataset.resumes), len(dataset.jobs), len(dataset.pairs)) == (1, 1, 1)
    assert load_dataset().name == "development"


def test_cli_runs_on_another_data_dir(
    tiny_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tiny_results"
    argv = ["--data-dir", str(tiny_dataset), "--formats", "docx", "--out", str(out)]
    assert run.main(argv) == 0
    printed = capsys.readouterr().out
    assert "on the tiny_set set" in printed
    results = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert results["meta"]["dataset"] == {
        "name": "tiny_set",
        "source": tiny_dataset.resolve().as_posix(),
        "development": False,
        "factcheck_labels": False,
    }
    assert results["comparison"] is None  # no baseline for this set
    pairs_overall = results["metrics"]["pairs"]["exact"]["overall"]
    assert pairs_overall["status_accuracy"] == {"rate": 1.0, "count": 3, "total": 3}
    assert results["metrics"]["requirements"]["rules"]["extraction_precision"]["rate"] == 1.0
    assert results["metrics"]["structure"]["overall"]["role_recall"]["rate"] == 1.0

    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert report.startswith("# Evaluation report: tiny_set set\n")
    assert "This set has no fact-check labels" in report
    assert "## Before and after" not in report
    assert "optimistic" not in report.split("## Known weaknesses")[0]

    # --check compares with the development thresholds and leaves out the fact checker.
    assert run.main([*argv, "--check"]) in (0, 1)
    printed = capsys.readouterr().out
    assert "thresholds were set on the development set" in printed
    assert "no fact-check labels" in printed
    assert "factcheck." not in printed


def test_output_folder_depends_on_the_data_dir(tiny_dataset: Path, tmp_path: Path) -> None:
    assert run.output_dir(run.DATA_DIR, None) == run.RESULTS_DIR
    assert run.output_dir(tiny_dataset, None) == run.RESULTS_DIR / "tiny_set"
    assert run.output_dir(tiny_dataset, tmp_path) == tmp_path
    assert run.parse_args([]).data_dir == run.DATA_DIR
    assert run.parse_args(["--data-dir", str(tiny_dataset)]).data_dir == tiny_dataset


def test_comparison_lists_earlier_runs_on_the_development_set(
    default_results: dict[str, object], tmp_path: Path
) -> None:
    compared = default_results["comparison"]
    assert isinstance(compared, dict)
    assert [r["label"] for r in compared["runs"]] == ["v0.4.0", "v0.4.0 app, v0.5 PDF builder"]
    paths = [row["path"] for row in compared["rows"]]
    assert "pairs.exact.overall.status_accuracy" in paths
    assert all(len(row["before"]) == 2 for row in compared["rows"])
    report = render_report(default_results)
    assert "| Metric | v0.4.0 | v0.4.0 app, v0.5 PDF builder | This run (" in report

    # A set without a baseline file has no comparison.
    metrics = default_results["metrics"]
    assert isinstance(metrics, dict)
    assert run.comparison(load_dataset().limited(1), metrics, tmp_path) is None


def test_a_baseline_can_name_this_run_and_say_why_it_isnt_blind(
    tiny_dataset: Path, tmp_path: Path
) -> None:
    dataset = load_dataset(tiny_dataset)
    results, _ = run.evaluate(dataset, run.Options(families=("docx",)), run_date=RUN_DATE)
    old_metrics = {"pairs.exact.overall.status_accuracy": {"rate": 0.5, "count": 1, "total": 2}}
    baseline = {
        "dataset": "tiny_set",
        "current_label": "v1.0 (after fixes informed by one example)",
        "caveat": "This set is no longer fully unseen.",
        "runs": [{"label": "v0.5 (blind)", "note": "Blind.", "metrics": old_metrics}],
    }
    (tmp_path / "tiny_set.json").write_text(json.dumps(baseline), encoding="utf-8")
    compared = run.comparison(dataset, results["metrics"], tmp_path)
    assert compared is not None
    # The fact checker isn't measured on this set (0/0 everywhere), so it has no row.
    assert all(not row["path"].startswith("factcheck.") for row in compared["rows"])
    report = render_report({**results, "comparison": compared})
    assert "| Metric | v0.5 (blind) | v1.0 (after fixes informed by one example) |" in report
    assert "## Before and after, tiny_set set\n\nThis set is no longer fully unseen." in report
    weaknesses = report.split("## Known weaknesses of this evaluation")[1]
    assert "- This set is no longer fully unseen." in weaknesses
