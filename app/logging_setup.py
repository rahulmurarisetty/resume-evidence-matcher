"""JSON logs.

Logs carry user ids but never emails, passwords, tokens, resume text, job-description
text, prompts or keys. Every field comes from the list below, and an error's
traceback is kept without its message, because messages from libraries can quote
input (a database error can quote an email, a validation error a line of a
resume). Messages of the app's own startup errors and of network errors are kept.
"""

import json
import logging
import traceback
from datetime import UTC, datetime
from types import TracebackType

from app.errors import StartupError

_EXTRA_FIELDS = (
    "request_id",
    "user_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "analysis_id",
    "analyses",
    "file_type",
    "bytes",
    "spans",
    "requirements",
    "purged",
    "sessions",
    "matching_mode",
    "auth_mode",
    "scanner",
    "signature",
    "action",
    "limited_by",
    "retry_after",
    "revision",
    "from_revision",
    "model",
    "llm",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "stop_reason",
    "error",
    "parser",
    "dropped",
    "dropped_skills",
    "calls",
    "generated",
    "rejected",
    "suggestions",
    "llm_consent",
)
# These libraries log request bodies (prompts and resume text) at DEBUG and every
# request line at INFO. Keep them at WARNING whatever LOG_LEVEL says.
_QUIET_LOGGERS = ("anthropic", "httpx", "httpx2", "httpcore", "httpcore2")
# Errors whose messages are written by the app or the network stack, not from input.
_SAFE_MESSAGES: tuple[type[BaseException], ...] = (StartupError, OSError)
HIDDEN = "(message hidden: it may quote user input)"


def format_exception(error: BaseException) -> str:
    """The traceback of `error` and the errors it was raised from, with each
    message replaced unless it is one of the safe kinds."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and all(current is not seen for seen in chain):
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    parts: list[str] = []
    for item in reversed(chain):
        if parts:
            parts.append("\nThe error above led to:\n")
        tb: TracebackType | None = item.__traceback__
        parts.append("Traceback (most recent call last):\n")
        parts.extend(traceback.format_list(traceback.extract_tb(tb)))
        kind = f"{type(item).__module__}.{type(item).__qualname__}"
        message = str(item) if isinstance(item, _SAFE_MESSAGES) else HIDDEN
        parts.append(f"{kind}: {message}\n")
    return "".join(parts)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[1] is not None:
            payload["exc_type"] = type(record.exc_info[1]).__name__
            payload["exc"] = format_exception(record.exc_info[1])
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log would duplicate the request log written by our middleware.
    logging.getLogger("uvicorn.access").disabled = True
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
