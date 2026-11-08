"""Run the app's own pipeline over the evaluation set.

Every resume is rendered once per format with tests/builders.py and then read by
the same functions the API uses: extract_resume and parse_profile for structure,
the job parser for requirements, and analyze for each resume and job pair. The
labels' as_of date is passed as "today" everywhere the app accepts one
(parse_profile and analyze), so current roles are counted to the same month as
the labels.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.models import AnalysisReport, ResumeDocument
from app.services.analysis import analyze
from app.services.extraction import extract_resume
from app.services.jd_parser import JobParser, ParsedJob, RuleJobParser
from app.services.semantic import DEFAULT_THRESHOLD, DEFAULT_TOP_K, Encoder, Reranker
from app.services.skills import SkillCatalog
from app.services.structure import parse_profile
from evals.dataset import Dataset, GoldPair
from evals.formats import Format
from evals.pairs import ItemOutcome, evaluate_pair
from evals.requirements import JobExtraction, evaluate_job
from evals.resume_structure import ResumeStructure, evaluate_resume


class Renderer:
    """Renders each (format, resume) once and keeps the bytes."""

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self._files: dict[tuple[str, str], bytes] = {}

    def file(self, fmt: Format, resume: str) -> bytes:
        key = (fmt.name, resume)
        if key not in self._files:
            self._files[key] = fmt.render(self.dataset.resumes[resume].markup)
        return self._files[key]


def run_structure(
    dataset: Dataset, formats: Sequence[Format], renderer: Renderer
) -> list[ResumeStructure]:
    results: list[ResumeStructure] = []
    for fmt in formats:
        for name, gold in dataset.resumes.items():
            document = extract_resume(renderer.file(fmt, name))
            profile = parse_profile(document, today=gold.as_of)
            results.append(evaluate_resume(gold, document, profile, fmt.name))
    return results


class CachedJobParser:
    """Parses each job description once. Keeps the Claude parser to one call per
    job however many resumes and formats are measured against it."""

    def __init__(self, inner: JobParser) -> None:
        self.inner = inner
        self._cache: dict[str, ParsedJob] = {}

    def parse(self, raw: str, catalog: SkillCatalog) -> ParsedJob:
        if raw not in self._cache:
            self._cache[raw] = self.inner.parse(raw, catalog)
        return self._cache[raw]


def run_requirements(
    dataset: Dataset, parser: JobParser, catalog: SkillCatalog
) -> tuple[list[JobExtraction], dict[str, ParsedJob]]:
    results: list[JobExtraction] = []
    parsed_jobs: dict[str, ParsedJob] = {}
    for name, gold in dataset.jobs.items():
        parsed = parser.parse(gold.text, catalog)
        parsed_jobs[name] = parsed
        results.append(evaluate_job(gold, parsed.job, parsed_name(parsed)))
    return results, parsed_jobs


def parsed_name(parsed: ParsedJob) -> str:
    """The parser that actually produced the requirements: "claude", "rules", or
    "rules" with the reason when the Claude parser fell back."""
    if parsed.parser.fallback_reason:
        return f"rules (fallback: {parsed.parser.fallback_reason})"
    return parsed.parser.name.value


@dataclass
class PairRun:
    pair: GoldPair
    format: str
    resume: ResumeDocument
    report: AnalysisReport


def run_pairs(
    dataset: Dataset,
    formats: Sequence[Format],
    renderer: Renderer,
    catalog: SkillCatalog,
    *,
    job_parser: JobParser | None = None,
    encoder: Encoder | None = None,
    reranker: Reranker | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    today: date | None = None,
) -> list[PairRun]:
    parser = job_parser or RuleJobParser()
    runs: list[PairRun] = []
    for fmt in formats:
        for pair in dataset.pairs:
            resume, report = analyze(
                renderer.file(fmt, pair.resume),
                dataset.jobs[pair.job].text,
                catalog=catalog,
                encoder=encoder,
                reranker=reranker,
                semantic_top_k=DEFAULT_TOP_K,
                semantic_threshold=threshold,
                today=today or dataset.resumes[pair.resume].as_of,
                job_parser=parser,
            )
            runs.append(PairRun(pair, fmt.name, resume, report))
    return runs


def score_pairs(dataset: Dataset, runs: Sequence[PairRun], mode: str) -> list[ItemOutcome]:
    outcomes: list[ItemOutcome] = []
    for run in runs:
        outcomes.extend(
            evaluate_pair(run.pair, dataset.jobs[run.pair.job], run.report, run.format, mode)
        )
    return outcomes
