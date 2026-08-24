"""
Structured logging with request/run correlation.

Every log line carries the request_id and run_id that were in scope when it was
emitted, so a single run can be traced across the webhook, the graph, and the
tool layer. Output is JSON in production and human-readable locally.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import sys
import uuid
from typing import Any, ClassVar

from app.config import settings
from app.core.redaction import redact

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class ContextFilter(logging.Filter):
    """Attach correlation ids to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # LogRecord has no declared slots for these; the formatters read
        # them back off __dict__.
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        record.run_id = run_id_var.get()  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "service": settings.SERVICE_NAME,
            "env": settings.ENVIRONMENT,
        }
        # Set by ContextFilter; absent if a record bypassed the filter.
        if request_id := getattr(record, "request_id", ""):
            payload["request_id"] = request_id
        if run_id := getattr(record, "run_id", ""):
            payload["run_id"] = run_id
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload.setdefault(key, value)

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    _COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[38;5;244m",
        "INFO": "\033[38;5;39m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;203m",
        "CRITICAL": "\033[48;5;203m\033[38;5;231m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        ts = dt.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        run = getattr(record, "run_id", "")
        suffix = f" \033[38;5;244m[run:{run[:8]}]{self._RESET}" if run else ""
        base = (
            f"{ts} {color}{record.levelname:<8}{self._RESET} "
            f"\033[38;5;244m{record.name}{self._RESET}{suffix} "
            f"{redact(record.getMessage())}"
        )
        if record.exc_info:
            base += "\n" + redact(self.formatException(record.exc_info))
        return base


def configure_logging() -> None:
    """Install handlers. Safe to call more than once."""
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.LOG_FORMAT == "json" else ConsoleFormatter())
    handler.addFilter(ContextFilter())

    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)

    # These are chatty and rarely useful at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "e2b"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
