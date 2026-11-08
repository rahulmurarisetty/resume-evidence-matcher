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
from app.api.errors import install_error_handlers
from app.api.routes import router
from app.config import Settings, get_settings
from app.logging_setup import configure_logging
from app.services.skills import get_catalog
from app.storage.db import Database, init_db
from app.storage.repository import AnalysisRepository

logger = logging.getLogger("app")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Room for the multipart envelope and the job-description field on top of the file.
_FORM_OVERHEAD_BYTES = 256 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    # Starlette writes uploads larger than 1 MB to a temporary file. Keep files up to
    # our limit in memory instead, so resumes never touch the disk.
    MultiPartParser.spool_max_size = settings.max_upload_bytes + 1

    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(db.engine)
        for session in db.session():
            purged = AnalysisRepository(session).purge_expired()
        logger.info("startup complete", extra={"purged": purged})
        get_catalog()  # load the skill catalog before the first request
        yield
        db.engine.dispose()

    app = FastAPI(
        title="Resume Evidence Matcher",
        version=__version__,
        description=(
            "Maps each job-description requirement to the resume lines that support it, "
            "marks gaps, and never invents experience."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
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
            response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    install_error_handlers(app)
    app.include_router(router)
    return app
