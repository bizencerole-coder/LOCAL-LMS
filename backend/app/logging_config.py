"""Logging setup with request IDs.

Log records never include passwords, bearer tokens or signed media URLs. Pass
structured fields with ``log_event(logger, "event_name", key=value)``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _TextFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields: dict[str, Any] | None = getattr(record, "fields", None)
        if fields:
            line += " " + " ".join(f"{k}={_text_value(v)}" for k, v in fields.items())
        return line


_PLAIN_VALUE_RE = re.compile(r"^[A-Za-z0-9._:/@+-]*$")


def _text_value(value: Any) -> str:
    # Quote and escape anything that could be mistaken for another key=value pair or
    # line (request paths are client-controlled).
    text = str(value)
    return text if _PLAIN_VALUE_RE.match(text) else json.dumps(text)


class _JsonFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # Replaced by the access-log middleware, which omits query strings and adds request IDs.
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})
