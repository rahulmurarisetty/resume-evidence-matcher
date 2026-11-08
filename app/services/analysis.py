"""The full pipeline: file bytes and job-description text in, report out."""

from datetime import date

from app.models import AnalysisReport, ResumeDocument
from app.services.extraction import ExtractionLimits, extract_resume
from app.services.jd_parser import parse_job_description
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
) -> tuple[ResumeDocument, AnalysisReport]:
    """Run the pipeline. Matching by meaning runs when an encoder is given; the
    reranker is optional. `today` fixes the date used for current roles."""
    catalog = catalog or get_catalog()
    resume = extract_resume(resume_bytes, limits)
    job = parse_job_description(job_description, catalog)
    semantic = (
        SemanticMatcher(encoder, reranker, top_k=semantic_top_k, threshold=semantic_threshold)
        if encoder is not None
        else None
    )
    return resume, build_report(resume, job, catalog, semantic=semantic, today=today)
