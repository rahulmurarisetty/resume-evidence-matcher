"""The full pipeline: file bytes and job-description text in, report out."""

from app.models import AnalysisReport, ResumeDocument
from app.services.extraction import ExtractionLimits, extract_resume
from app.services.jd_parser import parse_job_description
from app.services.matcher import build_report
from app.services.skills import SkillCatalog, get_catalog


def analyze(
    resume_bytes: bytes,
    job_description: str,
    limits: ExtractionLimits | None = None,
    catalog: SkillCatalog | None = None,
) -> tuple[ResumeDocument, AnalysisReport]:
    catalog = catalog or get_catalog()
    resume = extract_resume(resume_bytes, limits)
    job = parse_job_description(job_description, catalog)
    return resume, build_report(resume, job, catalog)
