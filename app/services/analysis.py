"""The full pipeline: file bytes and job-description text in, report out."""

from datetime import date

from app.models import AnalysisReport, ResumeDocument
from app.services.extraction import ExtractionLimits, extract_resume
from app.services.jd_parser import JobParser, RuleJobParser
from app.services.matcher import build_report
from app.services.semantic import (
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
    Encoder,
    Reranker,
    SemanticMatcher,
)
from app.services.skills import SkillCatalog, get_catalog


def analyze(
    resume_bytes: bytes,
    job_description: str,
    limits: ExtractionLimits | None = None,
    catalog: SkillCatalog | None = None,
    *,
    encoder: Encoder | None = None,
    reranker: Reranker | None = None,
    semantic_top_k: int = DEFAULT_TOP_K,
    semantic_threshold: float = DEFAULT_THRESHOLD,
    today: date | None = None,
    job_parser: JobParser | None = None,
) -> tuple[ResumeDocument, AnalysisReport]:
    """Run the pipeline. Matching by meaning runs when an encoder is given; the
    reranker is optional. `today` fixes the date used for current roles. The rule
    parser reads the job description unless another `job_parser` is given."""
    catalog = catalog or get_catalog()
    resume = extract_resume(resume_bytes, limits)
    parsed = (job_parser or RuleJobParser()).parse(job_description, catalog)
    semantic = (
        SemanticMatcher(encoder, reranker, top_k=semantic_top_k, threshold=semantic_threshold)
        if encoder is not None
        else None
    )
    report = build_report(resume, parsed.job, catalog, semantic=semantic, today=today)
    report = report.model_copy(
        update={"job_parser": parsed.parser, "warnings": [*parsed.warnings, *report.warnings]}
    )
    return resume, report
