"""Structured logging setup.

Emits single-line JSON in non-local environments (grep/aggregate friendly)
and readable colored-ish text locally. A contextvar carries the request id
so every log line inside a request can be correlated without threading it
through every function signature.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar

from app.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in ("args", "msg", "exc_info", "exc_text", "stack_info") or key in payload:
                continue
            if key.startswith("_"):
                continue
            if key in logging.LogRecord.__dict__:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_ctx.get()
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} [{rid}] {record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.LOG_JSON else _TextFormatter())
    root.addHandler(handler)

    # Quiet the noisiest third-party loggers down a notch.
    for noisy in (
        "httpx",
        "httpcore",
        "fastembed",
        "onnxruntime",
        "urllib3",
        "botocore",
        "LiteLLM",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
