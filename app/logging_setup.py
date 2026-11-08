"""JSON logs. Resume text, job-description text, prompts and keys are never logged."""

import json
import logging
from datetime import UTC, datetime

_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "analysis_id",
    "file_type",
    "spans",
    "requirements",
    "purged",
    "matching_mode",
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
)
# These libraries log request bodies (prompts and resume text) at DEBUG and every
# request line at INFO. Keep them at WARNING whatever LOG_LEVEL says.
_QUIET_LOGGERS = ("anthropic", "httpx", "httpx2", "httpcore", "httpcore2")


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
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


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
