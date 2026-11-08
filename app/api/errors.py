from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.extraction import ExtractionError

# Extraction problems the user can fix map to these HTTP statuses.
_EXTRACTION_STATUS = {
    "unsupported_type": 415,
    "legacy_doc": 415,
    "file_too_large": 413,
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


def _body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            _body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(ExtractionError)
    async def _extraction_error(_: Request, exc: ExtractionError) -> JSONResponse:
        status = _EXTRACTION_STATUS.get(exc.code, 422)
        return JSONResponse(_body(exc.code, exc.message), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({str(err["loc"][-1]) for err in exc.errors() if err.get("loc")})
        message = (
            "Invalid or missing fields: " + ", ".join(fields) if fields else "Invalid request."
        )
        return JSONResponse(_body("invalid_request", message), status_code=422)
