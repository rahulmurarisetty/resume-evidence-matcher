import hashlib
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.api.schemas import AnalysisResponse, ErrorResponse, ExtractResponse, HealthResponse
from app.config import Settings
from app.models import AnalysisReport
from app.services.analysis import analyze
from app.services.extraction import ExtractionLimits, extract_resume
from app.storage.db import AnalysisRecord
from app.storage.repository import AnalysisRepository

logger = logging.getLogger("app.api")

router = APIRouter()

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (404, 413, 415, 422)
}


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def _limits(settings: Settings) -> ExtractionLimits:
    return ExtractionLimits(
        max_pdf_pages=settings.max_pdf_pages,
        max_docx_uncompressed_bytes=settings.max_docx_uncompressed_bytes,
    )


def _read_upload(upload: UploadFile, settings: Settings) -> bytes:
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(
            413, "file_too_large", f"The resume must be under {settings.max_upload_mb:g} MB."
        )
    if not data:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    return data


def _to_response(record: AnalysisRecord) -> AnalysisResponse:
    return AnalysisResponse(
        id=record.id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        report=AnalysisReport.model_validate_json(record.report_json),
    )


@router.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse, tags=["ops"])
def readyz(session: SessionDep) -> HealthResponse:
    try:
        AnalysisRepository(session).ping()
    except Exception as exc:
        logger.exception("database not ready")
        raise ApiError(503, "not_ready", "The database is not reachable.") from exc
    return HealthResponse(status="ready")


@router.post(
    "/api/v1/extract",
    response_model=ExtractResponse,
    responses=_ERRORS,
    tags=["resume"],
    summary="Show the text the app reads from a resume. Nothing is stored.",
)
def extract(settings: SettingsDep, resume: UploadFile = File(...)) -> ExtractResponse:
    data = _read_upload(resume, settings)
    return ExtractResponse(resume=extract_resume(data, _limits(settings)))


@router.post(
    "/api/v1/analyses",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    tags=["analyses"],
    summary="Match a resume against a job description.",
)
def create_analysis(
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
    resume: UploadFile = File(...),
    job_description: str = Form(...),
) -> AnalysisResponse:
    job_text = job_description.strip()
    if len(job_text) < 50:
        raise ApiError(422, "job_description_too_short", "Paste the full job description.")
    if len(job_text) > settings.max_jd_chars:
        raise ApiError(
            413,
            "job_description_too_long",
            f"The job description must be under {settings.max_jd_chars} characters.",
        )

    data = _read_upload(resume, settings)
    resume_doc, report = analyze(
        data,
        job_text,
        _limits(settings),
        # Built at startup; None when matching by meaning is off.
        encoder=request.app.state.encoder,
        reranker=request.app.state.reranker,
        semantic_top_k=settings.semantic_top_k,
        semantic_threshold=settings.semantic_threshold,
    )

    repo = AnalysisRepository(session)
    repo.purge_expired()
    record = repo.create(
        report,
        file_type=resume_doc.file_type,
        file_sha256=hashlib.sha256(data).hexdigest(),
        retention=timedelta(hours=settings.retention_hours),
    )
    logger.info(
        "analysis created",
        extra={
            "analysis_id": record.id,
            "file_type": resume_doc.file_type.value,
            "spans": len(resume_doc.spans),
            "requirements": len(report.matches),
            "matching_mode": report.matching_mode.value,
        },
    )
    response.headers["Location"] = f"/api/v1/analyses/{record.id}"
    return _to_response(record)


@router.get(
    "/api/v1/analyses/{analysis_id}",
    response_model=AnalysisResponse,
    responses=_ERRORS,
    tags=["analyses"],
)
def get_analysis(analysis_id: str, session: SessionDep) -> AnalysisResponse:
    record = AnalysisRepository(session).get(analysis_id)
    if record is None:
        raise ApiError(404, "not_found", "No analysis with that id, or it has expired.")
    return _to_response(record)


@router.delete(
    "/api/v1/analyses/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    tags=["analyses"],
    summary="Delete an analysis and everything stored with it.",
)
def delete_analysis(analysis_id: str, session: SessionDep) -> Response:
    if not AnalysisRepository(session).delete(analysis_id):
        raise ApiError(404, "not_found", "No analysis with that id.")
    logger.info("analysis deleted", extra={"analysis_id": analysis_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
