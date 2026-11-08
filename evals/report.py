"""Render REPORT.md from the results dict that is also written to latest.json, so
the two never disagree."""

from collections.abc import Sequence
from typing import Any

Row = Sequence[object]


def rate(value: dict[str, Any] | None) -> str:
    if value is None:
        return "not run"
    share = value["rate"]
    shown = "n/a" if share is None else f"{share * 100:.1f}%"
    return f"{shown} ({value['count']}/{value['total']})"


def number(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def table(headers: Sequence[str], rows: Sequence[Row]) -> list[str]:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
    return [*lines, ""]


def _code(text: str) -> str:
    return f"`{text}`"


def _matrix(confusion: dict[str, Any], row_title: str) -> list[str]:
    headers = [f"{row_title} \\ app", *confusion["predicted_labels"]]
    rows = [
        [label, *counts]
        for label, counts in zip(confusion["gold_labels"], confusion["rows"], strict=True)
        if any(counts)
    ]
    return table(headers, rows)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _run_section(results: dict[str, Any]) -> list[str]:
    meta = results["meta"]
    commit = meta["git_commit"] or "unknown"
    if meta["uncommitted_changes"]:
        commit += " with uncommitted changes"
    labels = meta["labels"]
    semantic, llm = results["semantic"], results["llm"]

    def mode(section: dict[str, Any]) -> str:
        if section["status"] == "skipped":
            return f"skipped: {section['reason']}"
        return str(section["status"])

    dataset = meta["dataset"]
    fact_cases = (
        f"{labels['factcheck_holdout']} held-out and {labels['factcheck_development']} "
        "development fact-check cases"
        if dataset["factcheck_labels"]
        else "no fact-check cases"
    )
    rows = [
        ("Dataset", f"{dataset['name']} (`{dataset['source']}`)"),
        ("Pipeline version", meta["pipeline_version"]),
        ("Git commit", commit),
        ("Labels as of", f"{meta['as_of']}, passed to the app as today"),
        ("Job parser", "rules (Claude only with --llm)"),
        ("Matching", "exact"),
        ("Matching by meaning (--semantic)", mode(semantic)),
        ("Claude parser and rewrites (--llm)", mode(llm)),
        (
            "Libraries",
            f"Python {meta['python']}, PyMuPDF {meta['pymupdf']}, "
            f"python-docx {meta['python_docx']}",
        ),
        (
            "Labels",
            f"{labels['resumes']} resumes ({labels['roles']} roles, "
            f"{labels['education_entries']} education entries), {labels['jobs']} jobs "
            f"({labels['job_requirements']} requirement lines), {labels['pairs']} pairs "
            f"({labels['pair_labels']} requirement labels), {fact_cases}",
        ),
    ]
    lines = ["## Run", "", *table(["Setting", "Value"], rows)]
    lines += table(
        ["Format", "How the file is made"],
        [(_code(f["name"]), f["description"]) for f in meta["formats"]],
    )
    lines += [
        '"Overall" pools the formats. The same resumes are read in each format, so it is not '
        "that many independent samples: a resume that fails in every format counts once per "
        "format.",
        "",
    ]
    return lines


def _headline_section(results: dict[str, Any]) -> list[str]:
    m = results["metrics"]
    s, r = m["structure"]["overall"], m["requirements"]["rules"]
    p, holdout = m["pairs"]["exact"]["overall"], m["factcheck"]["holdout"]
    rows = [
        ("Role detection recall (all formats)", rate(s["role_recall"])),
        ("Total years within 0.5 of the label", rate(s["total_years_within_half"])),
        ("Requirement extraction recall", rate(r["extraction_recall"])),
        ("Requirement extraction precision", rate(r["extraction_precision"])),
        ("Priority accuracy on extracted requirements", rate(r["priority_accuracy"])),
        ("Pair status accuracy (all formats)", rate(p["status_accuracy"])),
        (
            "False proven: app says direct, label says gap or needs_check",
            rate(p["false_proven_rate"]),
        ),
        ("Evidence recall@3", rate(p["evidence_recall_at_3"])),
        ("Fact checker accuracy, held-out set", rate(holdout["accuracy"])),
        ("Fact checker false passes, held-out set", rate(holdout["false_pass_rate"])),
    ]
    return ["## Headline numbers", "", *table(["Metric", "Result"], rows)]


def _format_columns(section: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    names = list(section["by_format"])
    return [*names, "overall"], [*(section["by_format"][n] for n in names), section["overall"]]


def _structure_section(results: dict[str, Any]) -> list[str]:
    section = results["metrics"]["structure"]
    columns, values = _format_columns(section)
    metrics = [
        ("Role precision", "role_precision"),
        ("Role recall", "role_recall"),
        ("Start month correct (matched roles)", "start_month_accuracy"),
        ("End month correct (matched roles)", "end_month_accuracy"),
        ("Resumes with total years read", "total_years_measured"),
        ("Total years within 0.5", "total_years_within_half"),
        ("Education recall", "education_recall"),
        ("Education precision", "education_precision"),
        ("Education year correct (matched entries)", "education_year_accuracy"),
    ]
    rows: list[list[object]] = [[label, *(rate(v[key]) for v in values)] for label, key in metrics]
    rows.insert(
        6,
        [
            "Total years mean absolute error (resumes with a value)",
            *(number(v["total_years_mae"]) for v in values),
        ],
    )
    lines = [
        "## Resume structure",
        "",
        "A predicted role matches a labeled role when both its title and its employer match "
        "(equal after normalizing case and punctuation, or a fuzzy ratio of at least "
        f"{results['meta']['fuzzy_threshold']}). Months are compared on matched roles. "
        "Total years counts as within 0.5 only when the app gives a number.",
        "",
        *table(["Metric", *columns], rows),
    ]

    per_resume = results["details"]["structure_per_resume"]
    formats = list(section["by_format"])
    by_resume: dict[str, dict[str, dict[str, Any]]] = {}
    for row in per_resume:
        by_resume.setdefault(row["resume"], {})[row["format"]] = row
    resume_rows = []
    for resume, rows_by_format in by_resume.items():
        first = next(iter(rows_by_format.values()))
        resume_rows.append(
            [
                resume,
                first["roles_gold"],
                " / ".join(
                    str(rows_by_format[f]["roles_matched"]) if f in rows_by_format else "-"
                    for f in formats
                ),
                number(first["years_gold"], 1),
                " / ".join(
                    number(rows_by_format[f]["years_app"], 1) if f in rows_by_format else "-"
                    for f in formats
                ),
            ]
        )
    order = " / ".join(formats)
    lines += [
        f"Per resume, with one value per format ({order}):",
        "",
        *table(
            ["Resume", "Labeled roles", "Roles matched", "Labeled years", "Years read"],
            resume_rows,
        ),
    ]
    return lines


def _requirements_section(results: dict[str, Any]) -> list[str]:
    reqs = results["metrics"]["requirements"]
    parsers = [("rules", reqs["rules"])]
    if reqs.get("claude"):
        parsers.append(("claude", reqs["claude"]))
    headers = ["Metric", *(name for name, _ in parsers)]
    metric_rows = [
        ("Extraction precision (extracted items that are labeled lines)", "extraction_precision"),
        ("Extraction recall (labeled lines found)", "extraction_recall"),
        ("Priority accuracy on matched items", "priority_accuracy"),
        ("Job minimum years correct", "min_years_accuracy"),
        ("Job title correct", "title_accuracy"),
    ]
    lines = [
        "## Requirement extraction",
        "",
        "Extracted requirement texts are matched one to one with the labeled lines after "
        "normalizing case, whitespace and punctuation: equal, one containing the other, or a "
        "fuzzy ratio of at least 0.85. The job descriptions are plain text, so these numbers "
        "don't depend on the resume format.",
        "",
        *table(
            headers, [[label, *(rate(p[key]) for _, p in parsers)] for label, key in metric_rows]
        ),
    ]
    rules = reqs["rules"]
    kinds = rules["match_kinds"]
    lines += [
        f"Rule parser matches: {kinds['exact']} exact, {kinds['contains']} by containment, "
        f"{kinds['fuzzy']} fuzzy.",
        "",
        "Per class, counting lines that weren't extracted against recall and extracted lines "
        "that aren't requirements against precision:",
        "",
        *table(
            ["Class", "Precision", "Recall"],
            [
                [label, rate(values["precision"]), rate(values["recall"])]
                for label, values in rules["per_class"].items()
            ],
        ),
        "Confusion matrix for the rule parser (rows are labels, columns the parser's "
        "priority; not_a_requirement rows are extracted lines with no label):",
        "",
        *_matrix(rules["confusion"], "label"),
        "Per job:",
        "",
        *table(
            [
                "Job",
                "Labeled lines",
                "Extracted",
                "Matched",
                "Priority correct",
                "Min years (label / app)",
                "Title correct",
            ],
            [
                [
                    row["job"],
                    row["gold"],
                    row["predicted"],
                    row["matched"],
                    row["priority_correct"],
                    f"{row['min_years_gold']} / {row['min_years_app']}",
                    "yes" if row["title_ok"] else "no",
                ]
                for row in results["details"]["requirements_per_job"]
            ],
        ),
    ]
    return lines


_PAIR_METRICS = [
    ("Status accuracy", "status_accuracy"),
    ("False proven (direct where the label is gap or needs_check)", "false_proven_rate"),
    ("Share of direct calls that are false proven", "false_proven_share_of_direct"),
    ("Direct where the label isn't direct", "overclaim_rate"),
    ("Gap precision", "gap_precision"),
    ("Gap recall", "gap_recall"),
    ("Labeled requirement not extracted", "not_extracted"),
    ("Evidence recall@1", "evidence_recall_at_1"),
    ("Evidence recall@3", "evidence_recall_at_3"),
    ("Evidence recall@1 without years-only items", "evidence_recall_at_1_without_years_only"),
    ("Evidence recall@3 without years-only items", "evidence_recall_at_3_without_years_only"),
]


def _pairs_section(results: dict[str, Any]) -> list[str]:
    pair_metrics = results["metrics"]["pairs"]
    exact = pair_metrics["exact"]
    columns, values = _format_columns(exact)
    overall = exact["overall"]
    lines = [
        "## Evidence and status per pair",
        "",
        "Each labeled requirement in pairs.json is looked up in the app's report through the "
        "same text matching as above. The app's statuses map to the labels one to one, with "
        "not_assessed read as needs_check; a labeled requirement the parser didn't extract "
        "counts as not_extracted and is always wrong. Evidence recall looks at the first 1 or "
        "3 lines the report cites (exact evidence skill by skill, then related evidence) and "
        "counts a hit when a line contains a labeled evidence string or is contained in one. "
        "It covers labeled direct, partial and adjacent items that have evidence strings. "
        "Years-only requirements cite no lines in the report, so recall is also shown without "
        "them.",
        "",
        *table(
            ["Metric", *columns],
            [[label, *(rate(v[key]) for v in values)] for label, key in _PAIR_METRICS],
        ),
        "Confusion matrix, all formats (rows are labels, columns the app):",
        "",
        *_matrix(overall["confusion"], "label"),
        "Per status, all formats:",
        "",
        *table(
            ["Status", "Precision", "Recall"],
            [
                [status, rate(v["precision"]), rate(v["recall"])]
                for status, v in overall["per_status"].items()
            ],
        ),
        "Status accuracy by how well the resume fits the job (all formats):",
        "",
        *table(
            ["Fit", "Status accuracy"],
            [[fit, rate(v)] for fit, v in overall["status_accuracy_by_fit"].items()],
        ),
    ]
    per_pair: dict[str, dict[str, Any]] = {}
    formats = list(exact["by_format"])
    for row in results["details"]["pairs_per_pair"]:
        entry = per_pair.setdefault(row["pair"], {"fit": row["fit"], "items": row["items"]})
        entry[row["format"]] = row["correct"]
    lines += [
        f"Correct statuses per pair, one value per format ({' / '.join(formats)}):",
        "",
        *table(
            ["Pair", "Fit", "Labels", "Correct"],
            [
                [
                    pair,
                    entry["fit"],
                    entry["items"],
                    " / ".join(str(entry.get(f, "-")) for f in formats),
                ]
                for pair, entry in per_pair.items()
            ],
        ),
    ]

    compare = [("semantic", pair_metrics.get("semantic")), ("claude", pair_metrics.get("claude"))]
    ran = [(name, data) for name, data in compare if data]
    if ran:
        lines += [
            "Exact matching with the rule parser next to the other modes that ran (all formats):",
            "",
            *table(
                ["Metric", "exact, rules", *(f"{name}" for name, _ in ran)],
                [
                    [label, rate(overall[key]), *(rate(d["overall"][key]) for _, d in ran)]
                    for label, key in _PAIR_METRICS
                ],
            ),
        ]
    return lines


def _factcheck_table(result: dict[str, Any]) -> list[str]:
    return table(
        ["Category", "Label", "Correct"],
        [[row["category"], row["label"], rate(row["accuracy"])] for row in result["per_category"]],
    )


def _factcheck_section(results: dict[str, Any]) -> list[str]:
    if not results["meta"]["dataset"]["factcheck_labels"]:
        return [
            "## Fact checker",
            "",
            "This set has no fact-check labels (labels/factcheck.json and "
            "labels/factcheck_holdout.json), so the fact checker wasn't measured on it.",
            "",
        ]
    sets = results["metrics"]["factcheck"]
    holdout, dev = sets["holdout"], sets["development"]
    metric_rows = [
        ("Accuracy", "accuracy"),
        ("Precision (rejected rewrites that do add a fact)", "precision"),
        ("Recall (rewrites that add a fact and were rejected)", "recall"),
        ("False passes (adds_fact cases the checker passed)", "false_pass_rate"),
        ("False rejects (faithful cases the checker rejected)", "false_reject_rate"),
    ]
    lines = [
        "## Fact checker",
        "",
        'The positive class is "adds a fact": a rejected rewrite is a positive prediction. A '
        "false pass is the dangerous error, because that rewrite would be shown to the person. "
        "The held-out set is the primary result. The development set was used while building "
        "the checker, so its numbers are optimistic.",
        "",
        *table(
            [
                "Metric",
                f"Held-out set ({holdout['cases']} cases)",
                f"Development set, used while building the checker, so optimistic "
                f"({dev['cases']} cases)",
            ],
            [[label, rate(holdout[key]), rate(dev[key])] for label, key in metric_rows],
        ),
        "### Held-out set by category",
        "",
        *_factcheck_table(holdout),
        "### Development set by category (used while building the checker, so optimistic)",
        "",
        *_factcheck_table(dev),
        "### Every disagreement",
        "",
    ]
    disagreements = results["details"]["factcheck_disagreements"]
    any_listed = False
    for name, title in (("holdout", "held-out"), ("development", "development")):
        for case in disagreements[name]:
            any_listed = True
            reasons = "; ".join(case["checker_reasons"]) or "none"
            added = ", ".join(f'"{a}"' for a in case["gold_added"]) or "none"
            lines += [
                f"{case['id']} ({title} set, {case['category']}): labeled {case['gold']}, "
                f"the checker {case['checker']} it.",
                "",
                f"- Source: {case['source']}",
                f"- Rewrite: {case['rewrite']}",
                f"- Added facts in the label: {added}",
                f"- The checker's reasons: {reasons}",
                "",
            ]
    if not any_listed:
        lines += ["The checker agrees with every label in both sets.", ""]
    return lines


def _comparison_section(results: dict[str, Any]) -> list[str]:
    compared = results.get("comparison")
    if not compared:
        return []
    dataset = results["meta"]["dataset"]
    runs = compared["runs"]
    current = f"This run ({results['meta']['pipeline_version']})"
    if dataset["development"]:
        heading = (
            "## Before and after, development set (used to find and fix these failures, so "
            "these numbers are optimistic)"
        )
        lead = (
            "v0.5 was built by reading this set's failures, so its gains here are optimistic. "
            "The held-out numbers in the README come from a set that wasn't used for v0.5. "
        )
    else:
        heading = f"## Before and after, {dataset['name']} set"
        lead = ""
    lines = [
        heading,
        "",
        f"{lead}Each earlier run is kept in `evals/baselines/{dataset['name']}.json`.",
        "",
    ]
    lines += [f"- {run['label']}: {run['note']}" for run in runs]
    lines.append("")
    lines += table(
        ["Metric", *(run["label"] for run in runs), current],
        [
            [row["metric"], *(rate(value) for value in row["before"]), rate(row["now"])]
            for row in compared["rows"]
        ],
    )
    return lines


def _not_run(section: dict[str, Any], flag: str) -> str:
    if section["status"] == "skipped":
        return f"Not run in this evaluation: {flag} was given, but {section['reason']}"
    return f"Not run in this evaluation, because {flag} wasn't given."


def _semantic_section(results: dict[str, Any]) -> list[str]:
    section = results["semantic"]
    lines = ["## Matching by meaning", ""]
    if section["status"] != "ran":
        lines += [
            f"{_not_run(section, '--semantic')} In exact mode the app never returns adjacent, "
            "so every item labeled adjacent counts as an error above. "
            f"{section['how_to_run']}",
            "",
        ]
        return lines
    reranker = section["rerank_model"] or "no reranker (cosine similarity as the score)"
    lines += [
        f"Pairs scored with matching by meaning, embedding model {section['embedding_model']} "
        f"and reranker {reranker}, at several thresholds (all formats). The app's default "
        "threshold is 0.5. Reports where matching by meaning failed and fell back to exact "
        f"matching: {section['reports_without_semantic']}.",
        "",
        *table(
            [
                "Threshold",
                "Status accuracy",
                "Adjacent precision",
                "Adjacent recall",
                "False proven",
                "Evidence recall@3",
            ],
            [
                [
                    row["threshold"],
                    rate(row["status_accuracy"]),
                    rate(row["adjacent_precision"]),
                    rate(row["adjacent_recall"]),
                    rate(row["false_proven_rate"]),
                    rate(row["evidence_recall_at_3"]),
                ]
                for row in section["threshold_sweep"]
            ],
        ),
    ]
    return lines


def _llm_section(results: dict[str, Any]) -> list[str]:
    section = results["llm"]
    lines = ["## Claude parser and rewrites", ""]
    if section["status"] != "ran":
        lines += [
            f"{_not_run(section, '--llm')} No call was made to a model provider. "
            f"{section['how_to_run']}",
            "",
        ]
        return lines
    rewrites = section["rewrites"]
    lines += [
        f"Parser model {section['parse_model']}, rewrite model {section['rewrite_model']}. "
        "The parser's numbers are in the requirement extraction and pair tables above. "
        f"Rewrites were generated for the {section['rewrite_format']} reports and saved to "
        "llm_candidates.json for review.",
        "",
        *table(
            ["Job", "Parser used", "Requirements dropped by the checks"],
            [
                [job, parser, section["dropped_requirements"].get(job, 0)]
                for job, parser in section["parsers_used"].items()
            ],
        ),
        *table(
            ["Rewrite step", "Value"],
            [
                ("Pairs", rewrites["pairs"]),
                ("Calls to Claude", rewrites["calls"]),
                ("Candidates returned", rewrites["candidates"]),
                ("Kept by the fact checker", rewrites["kept"]),
                ("Rejected by the fact checker", rewrites["rejected"]),
                ("Empty, unchanged or repeated", rewrites["unchanged"]),
                ("Rejection rate (of checked candidates)", rate(rewrites["rejection_rate"])),
                (
                    "Rejections by kind of added fact",
                    ", ".join(f"{k} {v}" for k, v in rewrites["rejections_by_kind"].items())
                    or "none",
                ),
                (
                    "Requirements skipped",
                    ", ".join(f"{k} {v}" for k, v in rewrites["skipped"].items()) or "none",
                ),
                (
                    "Tokens in and out",
                    f"{rewrites['input_tokens']} and {rewrites['output_tokens']}",
                ),
                ("Counts match the app's own rewrite step", rewrites["matches_app_counts"]),
            ],
        ),
        *table(
            [
                "Pair",
                "Bullets chosen",
                "Candidates",
                "Kept",
                "Rejected",
                "Rejected for",
                "Unchanged",
            ],
            [
                [
                    row["pair"],
                    row["targets"],
                    row["candidates"],
                    row["kept"],
                    row["rejected"],
                    ", ".join(f"{k} {v}" for k, v in row["rejections_by_kind"].items()) or "-",
                    row["unchanged"],
                ]
                for row in rewrites["per_pair"]
            ],
        ),
    ]
    return lines


def _error_section(results: dict[str, Any]) -> list[str]:
    patterns = results["error_analysis"]
    recurring = [p for p in patterns if p["count"] >= 2]
    once = [p for p in patterns if p["count"] < 2]
    lines = [
        "## Error analysis",
        "",
        "Each pattern below is a rule over the default run's failures, and patterns are "
        "listed most frequent first. A count is of distinct labeled items: an item that fails "
        "in several formats counts once, and the formats are named. The text says what was "
        "observed in the extracted lines and reports, not a confirmed root cause.",
        "",
    ]
    for pattern in recurring:
        where = f", {pattern['formats']}" if pattern["formats"] else ""
        lines += [
            f"### {pattern['title']}",
            "",
            f"{pattern['area']}: {pattern['count']} {pattern['unit']}{where}. "
            f"{pattern['observation']}",
            "",
        ]
        for example in pattern["examples"]:
            formats = f" ({example['formats']})" if example["formats"] else ""
            lines.append(f"- {example['where']}{formats}: {example['what']}")
        lines.append("")
    if once:
        lines += ["Seen once:", ""]
        for pattern in once:
            example = pattern["examples"][0]
            formats = f" ({example['formats']})" if example["formats"] else ""
            lines.append(f"- {pattern['title']}. {example['where']}{formats}: {example['what']}")
        lines.append("")
    return lines


def _weaknesses(results: dict[str, Any]) -> list[str]:
    meta = results["meta"]
    labels, dataset = meta["labels"], meta["dataset"]
    cases = labels["factcheck_holdout"] + labels["factcheck_development"]
    items = [
        f"The sample is small: {labels['resumes']} resumes, {labels['jobs']} job descriptions, "
        f"{labels['pairs']} pairs with {labels['pair_labels']} requirement labels, and "
        f"{cases} fact-check cases. One item moves a per-format pair rate by about half a "
        "point and a per-job rate by several points, and the three formats read the same "
        "resumes, so pooling them doesn't add independent evidence.",
    ]
    if dataset["development"]:
        items += [
            "The labels were written by the project team, alongside the fictional resumes and "
            "job descriptions, by people who know how the app works. The resumes are cleaner "
            "and more regular than real ones, and the labeling conventions in "
            "evals/data/README.md decide many borderline items (for example that every "
            "soft-skill line is needs_check and that an Environment line counts as work "
            "experience).",
            "v0.5 fixed the failure patterns this set showed: role layouts, job-description "
            "headings and boilerplate, catalog skills, and degree and certification "
            "requirements. The fixes were written as general rules, but they were checked "
            "against this set, so its numbers are optimistic. A held-out set is the fair test.",
        ]
    else:
        items.append(
            f"The labels of the {dataset['name']} set follow the conventions in "
            "evals/data/README.md. How far it differs from the development set in wording and "
            "layout decides how much this run says about real resumes."
        )
    if dataset["factcheck_labels"]:
        items.append(
            "The fact checker's development set was used while the checker was built, so its "
            "numbers are optimistic. The held-out set is the primary result, but it has "
            f"{labels['factcheck_holdout']} cases and was written by the same team."
        )
    items += [
        "Matching by meaning and the Claude parser and rewrites are not run in CI, and were "
        "not run for this report unless the run table says so. Exact mode can't produce "
        "adjacent, and the Claude path is only exercised against a fake client in the tests.",
        "Every PDF comes from one builder (tests/builders.py). Since v0.5 it embeds the font "
        "file, so characters such as the en dash reach the app as written. Real exports from "
        "Word, Google Docs or LaTeX, two-column layouts, tables and text boxes are not "
        "covered.",
        "The evaluation's own matching rules (a fuzzy ratio of 0.85, containment for "
        "requirement texts, strict title and employer matching for roles) are choices. Other "
        "rules would move some role and requirement matches.",
    ]
    return items


def _weaknesses_section(results: dict[str, Any]) -> list[str]:
    return [
        "## Known weaknesses of this evaluation",
        "",
        *(f"- {item}" for item in _weaknesses(results)),
        "",
    ]


def render_report(results: dict[str, Any]) -> str:
    dataset = results["meta"]["dataset"]
    if dataset["development"]:
        note = (
            " This is the development set, which was used to find and fix the failures v0.5 "
            "addresses, so its numbers are optimistic."
        )
    else:
        note = ""
    lines = [
        f"# Evaluation report: {dataset['name']} set",
        "",
        f"Run date: {results['meta']['date']}",
        "",
        "Written by `python -m evals.run` from `latest.json` in this folder. Every number "
        f"comes from the hand-labeled fictional set in `{dataset['source']}/`, read through the "
        f"app's own pipeline. Each rate is shown with its counts, as (count/total).{note}",
        "",
        *_run_section(results),
        *_headline_section(results),
        *_comparison_section(results),
        *_structure_section(results),
        *_requirements_section(results),
        *_pairs_section(results),
        *_factcheck_section(results),
        *_semantic_section(results),
        *_llm_section(results),
        *_error_section(results),
        *_weaknesses_section(results),
    ]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"
