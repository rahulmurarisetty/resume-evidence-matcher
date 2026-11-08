import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser

from app import __version__
from app.api.auth import router as auth_router
from app.api.edits import router as edits_router
from app.api.errors import install_error_handlers
from app.api.headers import apply_security_headers, install_docs
from app.api.routes import router
from app.config import Settings, get_settings
from app.errors import StartupError
from app.llm import LLMClient, start_llm
from app.logging_setup import configure_logging
from app.services.ratelimit import RateLimiter
from app.services.scanning import ClamAVScanner, Scanner
from app.services.semantic import (
    Encoder,
    Reranker,
    load_models,
    sentence_transformers_available,
)
from app.services.skills import get_catalog
from app.storage.accounts import AccountRepository
from app.storage.db import Database
from app.storage.migrations import ensure_current, upgrade
from app.storage.repository import AnalysisRepository

logger = logging.getLogger("app")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Room for the multipart envelope and the job-description field on top of the file.
_FORM_OVERHEAD_BYTES = 256 * 1024


def _route_path(request: Request) -> str:
    """The matched route's template ("/api/v1/analyses/{analysis_id}"), not the
    URL itself, so a path someone typed an email or other text into is never
    logged. Requests that match no route are logged as "unmatched"."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def start_semantic(settings: Settings) -> tuple[Encoder | None, Reranker | None]:
    """Load the models for matching by meaning, or return (None, None) when it is off.

    SEMANTIC_MATCHING=on fails loudly if the models can't be loaded. "auto" falls
    back to exact matching and logs why.
    """
    mode = settings.semantic_matching
    if mode == "off":
        return None, None
    if not sentence_transformers_available():
        if mode == "on":
            raise StartupError(
                "SEMANTIC_MATCHING=on needs sentence-transformers. Install the ml extra "
                '(pip install -e ".[ml]") or set SEMANTIC_MATCHING=off.'
            )
        return None, None
    try:
        return load_models(settings.embedding_model, settings.rerank_model)
    except Exception:
        if mode == "on":
            raise
        logger.exception("models for matching by meaning could not be loaded; it stays off")
        return None, None


def start_claude(settings: Settings) -> LLMClient | None:
    """The Claude client, or None when LLM_ENABLED is off or no key is set."""
    key = settings.anthropic_api_key
    return start_llm(
        settings.llm_enabled,
        key.get_secret_value() if key is not None else None,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def start_scanner(settings: Settings) -> Scanner | None:
    if settings.scanner == "off":
        return None
    return ClamAVScanner(
        settings.clamav_host, settings.clamav_port, timeout=settings.clamav_timeout_seconds
    )


def start_limiter(settings: Settings) -> RateLimiter | None:
    if not settings.rate_limits_enabled:
        return None
    return RateLimiter(settings.rates, ip_multiplier=settings.rate_limit_ip_multiplier)


def check_settings(settings: Settings) -> None:
    """Refuse to start on settings that aren't safe in production, and log the
    allowed but risky ones."""
    problems = settings.production_problems()
    if problems:
        for problem in problems:
            logger.error("unsafe production setting", extra={"error": problem})
        raise StartupError(
            "APP_ENV=production refuses to start:\n" + "\n".join(f"- {p}" for p in problems)
        )
    for warning in settings.startup_warnings():
        logger.warning(warning)


def prepare_database(db: Database, settings: Settings) -> None:
    """Upgrade the database (DB_AUTO_MIGRATE) or check that it needs no migration."""
    try:
        if settings.auto_migrate:
            upgrade(db.engine)
        else:
            ensure_current(db.engine)
    except StartupError as exc:
        logger.error("database not ready", extra={"error": str(exc)})
        raise


def create_app(
    settings: Settings | None = None,
    *,
    encoder: Encoder | None = None,
    reranker: Reranker | None = None,
    llm_client: LLMClient | None = None,
    scanner: Scanner | None = None,
) -> FastAPI:
    """Build the app. Tests pass `encoder` and `reranker` to skip loading real models,
    `llm_client` to use a fake Claude and `scanner` to use a fake scanner.
    LLM_ENABLED=off ignores `llm_client`, and SCANNER=off ignores `scanner`."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    check_settings(settings)

    # Starlette writes uploads larger than 1 MB to a temporary file. Keep files up to
    # our limit in memory instead, so resumes never touch the disk.
    MultiPartParser.spool_max_size = settings.max_upload_bytes + 1

    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            prepare_database(db, settings)
            for session in db.session():
                purged = AnalysisRepository(session).purge_expired()
                sessions = AccountRepository(session).purge_expired_sessions()
            get_catalog()  # load the skill catalog before the first request
            if app.state.encoder is None:
                # Warm the models now so the first analysis doesn't wait for a download.
                app.state.encoder, app.state.reranker = start_semantic(settings)
            if app.state.llm is None:
                app.state.llm = start_claude(settings)
            mode = "semantic" if app.state.encoder is not None else "exact"
            logger.info(
                "startup complete",
                extra={
                    "purged": purged,
                    "sessions": sessions,
                    "matching_mode": mode,
                    "llm": "on" if app.state.llm is not None else "off",
                    "auth_mode": settings.auth_mode,
                    "scanner": settings.scanner,
                },
            )
            yield
        finally:
            # Also on a failed startup, so no database connection is left open.
            db.engine.dispose()

    app = FastAPI(
        title="Resume Evidence Matcher",
        version=__version__,
        description=(
            "Maps each job-description requirement to the resume lines that support it, "
            "marks gaps, and never invents experience. Every endpoint under /api/v1 except "
            "register and login needs a session token: log in, then use Authorize."
        ),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.encoder = encoder
    app.state.reranker = reranker
    app.state.llm = llm_client if settings.llm_enabled != "off" else None
    app.state.scanner = (scanner or start_scanner(settings)) if settings.scanner != "off" else None
    app.state.limiter = start_limiter(settings)
    app.state.proxies = settings.proxies

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    max_body = settings.max_upload_bytes + settings.max_jd_chars * 4 + _FORM_OVERHEAD_BYTES

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        started = time.perf_counter()

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            response: Response = JSONResponse(
                {"error": {"code": "request_too_large", "message": "The upload is too large."}},
                status_code=413,
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Answered here, not by the server, so the response still gets its
                # headers. The log keeps the traceback but not the error's message.
                logger.exception("unhandled error", extra={"request_id": request_id})
                response = JSONResponse(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "Something went wrong on the server. Try again, and "
                            f"mention request id {request_id} if it keeps happening.",
                        }
                    },
                    status_code=500,
                )

        response.headers["X-Request-ID"] = request_id
        apply_security_headers(
            response.headers, request.url.path, production=settings.is_production
        )
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "user_id": getattr(request.state, "user_id", None),
                "method": request.method,
                "path": _route_path(request),
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    install_error_handlers(app)
    install_docs(app)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(edits_router)
    return app
