# Evaluation

This folder measures the app against a hand-labeled set of fictional resumes and job descriptions. It renders each resume into real PDF and DOCX files, runs them through the app's own pipeline and compares the results with the labels. It never changes how the app behaves, and the app is never tuned against these labels: a weakness the evaluation finds is recorded in the report, not patched to raise the number.

The labeled data and its conventions are described in [data/README.md](data/README.md). The latest results are in [results/REPORT.md](results/REPORT.md) and, with every number and failure, in `results/latest.json`.

## Running it

From the project folder, with the dev install from the main README:

```bash
python -m evals.run            # default: exact matching, rule parser, every format
python -m evals.run --check    # the same, and exit 1 if a metric is past its threshold
```

The default run takes a few seconds and makes no network calls. It writes `results/latest.json` and `results/REPORT.md`. Running it again on the same code writes the same files, apart from the run date.

| Option | What it does |
| --- | --- |
| `--formats pdf,docx` | Which renderings to measure. `pdf` covers both PDF layouts (the default `PdfStyle` and the "separate" bullet mode), `docx` the Word file. Default: both. |
| `--semantic` | Also scores the pairs with matching by meaning, at the default threshold of 0.5 and at 0.3, 0.4, 0.6 and 0.7, and shows exact and semantic results side by side. Needs sentence-transformers. |
| `--llm` | Also reads every job description with the Claude parser and asks Claude for rewrites of each pair's supporting bullets. Needs `ANTHROPIC_API_KEY`. |
| `--out DIR` | Where to write the results. Default: `evals/results`. |
| `--check` | Compares the run with `thresholds.json` and exits with status 1 when a metric is past its threshold. CI runs this in default mode. |

### Matching by meaning, locally

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu   # Linux without a GPU
pip install -e ".[dev,ml]"
python -m evals.run --semantic
```

The first run downloads the two models from Hugging Face, about 180 MB. Without sentence-transformers, or when the models can't be loaded, the run still finishes and the report says the mode was skipped and why. The threshold table in the report is the place to start when choosing `SEMANTIC_THRESHOLD`.

### Claude, locally

Put the key in your environment or in the local `.env` file (see "Turning on Claude" in the main README), then:

```bash
python -m evals.run --llm
```

This makes one parse call per job description and, for each pair, asks for rewrites until the pair has used `LLM_MAX_SUGGESTIONS` candidates (20 by default), so a full run is about 8 parse calls and up to 160 rewrite calls. `LLM_PARSE_MODEL`, `LLM_REWRITE_MODEL` and `LLM_TIMEOUT_SECONDS` are read from the same settings as the app. `LLM_ENABLED` is ignored here, because `--llm` is already the opt-in. Every candidate, with the fact checker's verdict and reasons, goes to `results/llm_candidates.json` for a person to read. Model output changes from run to run, so commit that file only when you mean to keep a reviewed sample.

Without a key the mode is skipped with a message and nothing is sent anywhere.

## What it measures

Every rate in the report is shown with its counts. "Overall" pools the three renderings of the same resumes, so it is not three times as many independent samples.

1. Resume structure: role precision and recall (title and employer both match, after normalizing case and punctuation or with a fuzzy ratio of at least 0.85), start and end months on matched roles, total years (mean absolute error and the share within 0.5 years), and education recall. The labels' `as_of` date, 2026-11-01, is passed to the app as today.
2. Requirement extraction: extracted requirement texts are matched one to one with the labeled lines (equal, one containing the other, or a fuzzy ratio of at least 0.85). Precision, recall, priority accuracy, per-class precision and recall with a confusion matrix, and the job's minimum years.
3. Evidence and status per pair: status accuracy, a confusion matrix, gap precision and recall, the false proven rate (the app says direct where the label says gap or needs_check, the most harmful error) and evidence recall at 1 and 3.
4. The fact checker on both labeled sets, with "adds a fact" as the positive class: accuracy, precision, recall, false passes, false rejects, a table per category and every disagreement. The held-out set is the primary result. The development set was used while building the checker and is labeled as optimistic.
5. With `--semantic` or `--llm`, the extra modes described above.

The report ends with an error analysis that groups the failures into recurring patterns, each with examples, and a list of known weaknesses of the evaluation itself.

## Thresholds

`thresholds.json` holds floors and ceilings for `--check`, keyed by dotted paths into the `metrics` part of `latest.json`. Floors sit 0.02 below the measured default-run values, rounded down. Ceilings sit at the measured value: the held-out false-pass rate of the fact checker may not rise above what was measured, and neither may the false proven rate.

When a change moves a number on purpose, run the evaluation, read the new report, and update `thresholds.json` and the results in the same commit.

## Files

```
run.py              command line, the run itself and the outputs
dataset.py          loads the labels in data/
formats.py          the PDF and DOCX renderings (tests/builders.py)
pipeline.py         runs the app's own extraction, structure, parser and analysis
matching.py         text normalization, fuzzy matching and one-to-one alignment
metrics.py          rates with counts, confusion matrices
resume_structure.py, requirements.py, pairs.py, factcheck.py
                    the four evaluations
semantic_mode.py    --semantic
llm_mode.py         --llm
errors.py           failure patterns for the error analysis
report.py           REPORT.md
thresholds.py       --check
thresholds.json     the floors and ceilings
results/            latest.json and REPORT.md from the last default run
data/               the labeled set
```

The evaluation's own tests are in `tests/evals/`. They check the matching and metric functions on small hand-made inputs and run a smoke evaluation on two pairs. They use the fake models and the fake Claude client from `tests/fakes.py`, never the real ones.
