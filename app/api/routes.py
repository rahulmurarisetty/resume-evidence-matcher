import hashlib
import json
import logging
from datetime import timedelta

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status

from app.api.deps import SessionDep, SettingsDep, UserDep, enforce_limit
from app.api.errors import ApiError
from app.api.schemas import (
    AnalysisListResponse,
    AnalysisResponse,
    AnalysisSummary,
    ConsentNoticeOut,
    ConsentOut,
    ErrorResponse,
    ExtractResponse,
    HealthResponse,
)
from app.config import Settings
from app.models import AnalysisReport, CategoryCoverage
from app.services.analysis import analyze
from app.services.claude_jd_parser import ClaudeJobParser
from app.services.consent import CONSENT_REQUIRED, CONSENT_VERSION, consent_notice
from app.services.extraction import ExtractionLimits, extract_resume
from app.services.jd_parser import JobParser, RuleJobParser
from app.services.scanning import Scanner, ScannerUnavailable
from app.storage.db import AnalysisRecord
from app.storage.repository import AnalysisRepository

logger = logging.getLogger("app.api")

router = APIRouter()

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (401, 404, 413, 415, 422, 429, 503)
}
_NOT_FOUND = "No analysis with that id, or it has expired."


def _limits(settings: Settings) -> ExtractionLimits:
    return ExtractionLimits(
        max_pdf_pages=settings.max_pdf_pages,
        max_docx_uncompressed_bytes=settings.max_docx_uncompressed_bytes,
    )


def _read_upload(request: Request, upload: UploadFile, settings: Settings, user_id: str) -> bytes:
    """The uploaded bytes, after the size checks and the malware scan."""
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise ApiError(
            413, "file_too_large", f"The resume must be under {settings.max_upload_mb:g} MB."
        )
    if not data:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    _scan(request.app.state.scanner, data, user_id)
    return data


def _scan(scanner: Scanner | None, data: bytes, user_id: str) -> None:
    """Scan before the file is opened. Fails closed: no answer means no upload."""
    if scanner is None:
        return
    try:
        result = scanner.scan(data)
    except ScannerUnavailable as exc:
        logger.error("scanner unavailable", extra={"user_id": user_id, "error": str(exc)})
        raise ApiError(
            503,
            "scanner_unavailable",
            "Uploads are paused because the virus scanner can't be reached. Try again in a "
            "few minutes.",
            headers={"Retry-After": "30"},
        ) from None
    if not result.clean:
        logger.warning(
            "upload rejected by scanner",
            extra={"user_id": user_id, "signature": result.signature, "bytes": len(data)},
        )
        raise ApiError(
            422,
            "malware_detected",
            "The virus scanner flagged this file, so it was rejected and nothing was stored. "
            "If you think that's wrong, save the resume again from your editor as a new PDF "
            "or .docx file and upload that.",
        )


def _to_response(record: AnalysisRecord) -> AnalysisResponse:
    return AnalysisResponse(
        id=record.id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        consent=ConsentOut(
            given_at=record.consent_at,
            version=record.consent_version,
            llm=bool(record.llm_consent),
        ),
        report=AnalysisReport.model_validate_json(record.report_json),
    )


@router.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse, tags=["ops"])
def readyz(request: Request, session: SessionDep) -> HealthResponse:
    """Ready when the database answers and, with SCANNER=clamav, clamd does too."""
    try:
        AnalysisRepository(session).ping()
    except Exception as exc:
        logger.exception("database not ready")
        raise ApiError(503, "not_ready", "The database is not reachable.") from exc
    scanner: Scanner | None = request.app.state.scanner
    if scanner is not None:
        try:
            scanner.ping()
        except ScannerUnavailable as exc:
            logger.warning("scanner not ready", extra={"error": str(exc)})
            raise ApiError(503, "not_ready", "The virus scanner is not reachable.") from None
    return HealthResponse(status="ready")


@router.get(
    "/api/v1/consent",
    response_model=ConsentNoticeOut,
    responses=_ERRORS,
    tags=["analyses"],
    summary="The consent notice to show before an upload, built from this server's settings.",
)
def get_consent_notice(request: Request, user: UserDep, settings: SettingsDep) -> ConsentNoticeOut:
    notice = consent_notice(
        settings,
        llm_available=request.app.state.llm is not None,
        scanning=request.app.state.scanner is not None,
    )
    return ConsentNoticeOut(
        version=notice.version,
        points=notice.points,
        checkbox=notice.checkbox,
        llm_available=notice.llm_available,
        llm_points=notice.llm_points,
        llm_checkbox=notice.llm_checkbox,
    )


@router.post(
    "/api/v1/extract",
    response_model=ExtractResponse,
    responses=_ERRORS,
    tags=["resume"],
    summary="Show the text the app reads from a resume. Nothing is stored.",
)
def extract(
    request: Request, user: UserDep, settings: SettingsDep, resume: UploadFile = File(...)
) -> ExtractResponse:
    # Same cost as an analysis (scan and parse), so it counts as one.
    enforce_limit(request, "analyses", user_id=user.id)
    data = _read_upload(request, resume, settings, user.id)
    return ExtractResponse(resume=extract_resume(data, _limits(settings)))


@router.get(
    "/api/v1/analyses",
    response_model=AnalysisListResponse,
    responses=_ERRORS,
    tags=["analyses"],
    summary="Your analyses that haven't expired, newest first.",
)
def list_analyses(user: UserDep, session: SessionDep) -> AnalysisListResponse:
    out: list[AnalysisSummary] = []
    for record in AnalysisRepository(session).list_for_owner(user.id):
        report = json.loads(record.report_json)
        required = report.get("coverage", {}).get("required")
        out.append(
            AnalysisSummary(
                id=record.id,
                created_at=record.created_at,
                expires_at=record.expires_at,
                job_title=report.get("job", {}).get("title"),
                pipeline_version=record.pipeline_version,
                required=CategoryCoverage.model_validate(required) if required else None,
            )
        )
    return AnalysisListResponse(analyses=out)


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
    user: UserDep,
    settings: SettingsDep,
    session: SessionDep,
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    consent: bool = Form(
        False, description="Must be true: the person agrees to the notice from GET /api/v1/consent"
    ),
    llm_consent: bool = Form(
        False,
        description="Whether Claude may see this person's resume and job text. Default false.",
    ),
) -> AnalysisResponse:
    if not consent:
        # Checked before anything is read, scanned or counted.
        raise ApiError(422, "consent_required", CONSENT_REQUIRED)
    enforce_limit(request, "analyses", user_id=user.id)
    job_text = job_description.strip()
    if len(job_text) < 50:
        raise ApiError(422, "job_description_too_short", "Paste the full job description.")
    if len(job_text) > settings.max_jd_chars:
        raise ApiError(
            413,
            "job_description_too_long",
            f"The job description must be under {settings.max_jd_chars} characters.",
        )

    data = _read_upload(request, resume, settings, user.id)
    # Built at startup; None when Claude is off. Without the person's consent for
    # Claude, the rules read the job description even when Claude is on. Consent given
    # while Claude is off is stored as false: no notice about Anthropic was shown.
    llm = request.app.state.llm
    use_claude = llm is not None and llm_consent
    job_parser: JobParser = (
        ClaudeJobParser(llm, settings.llm_parse_model) if use_claude else RuleJobParser()
    )
    resume_doc, report = analyze(
        data,
        job_text,
        _limits(settings),
        # Built at startup; None when matching by meaning is off.
        encoder=request.app.state.encoder,
        reranker=request.app.state.reranker,
        semantic_top_k=settings.semantic_top_k,
        semantic_threshold=settings.semantic_threshold,
        job_parser=job_parser,
    )

    repo = AnalysisRepository(session)
    repo.purge_expired()
    record = repo.create(
        report,
        owner_id=user.id,
        file_type=resume_doc.file_type,
        file_sha256=hashlib.sha256(data).hexdigest(),
        retention=timedelta(hours=settings.retention_hours),
        # The lines are kept for corrections and export, never the file itself.
        resume=resume_doc,
        consent_version=CONSENT_VERSION,
        llm_consent=use_claude,
    )
    logger.info(
        "analysis created",
        extra={
            "analysis_id": record.id,
            "user_id": user.id,
            "file_type": resume_doc.file_type.value,
            "spans": len(resume_doc.spans),
            "requirements": len(report.matches),
            "matching_mode": report.matching_mode.value,
            "parser": report.job_parser.name.value,
            "llm_consent": use_claude,
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
def get_analysis(analysis_id: str, user: UserDep, session: SessionDep) -> AnalysisResponse:
    # Another person's analysis is answered like a missing one, so ids reveal nothing.
    record = AnalysisRepository(session).get(analysis_id, user.id)
    if record is None:
        raise ApiError(404, "not_found", _NOT_FOUND)
    return _to_response(record)


@router.delete(
    "/api/v1/analyses/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    tags=["analyses"],
    summary="Delete an analysis and everything stored with it.",
)
def delete_analysis(analysis_id: str, user: UserDep, session: SessionDep) -> Response:
    if not AnalysisRepository(session).delete(analysis_id, user.id):
        raise ApiError(404, "not_found", "No analysis with that id.")
    logger.info("analysis deleted", extra={"analysis_id": analysis_id, "user_id": user.id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
