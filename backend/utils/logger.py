from __future__ import annotations

import copy
import hashlib
import logging
import re
import sys
from pathlib import Path

_SECRET_RE = re.compile(r"(?i)(?:authorization|bearer|api[_-]?key|token|cookie|password|secret)\s*[=:]\s*[^\s|,;]+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_SESSION_RE = re.compile(r"(?i)session_id=([^\s|,;]+)")
_FILENAME_RE = re.compile(r"(?i)filename=([^\s|,;]+)")


def safe_ref(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def safe_suffix(value: str | None) -> str:
    suffix = Path(value or "").suffix.lower()
    return suffix[:10] if suffix else "none"


def redact_log_message(message: str) -> str:
    message = _SESSION_RE.sub(lambda match: f"session_ref={safe_ref(match.group(1))}", message)
    message = _FILENAME_RE.sub(lambda match: f"extension={safe_suffix(match.group(1))}", message)
    message = _SECRET_RE.sub("<redacted-secret>", message)
    message = _EMAIL_RE.sub("<redacted-email>", message)
    return _UUID_RE.sub("<redacted-id>", message)


class RedactingFormatter(logging.Formatter):
    """Redact values before any custom backend logger writes to container stdout."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = redact_log_message(record.getMessage())
        safe_record.args = ()
        # Provider errors can contain response bodies; retain the event but never emit traceback text.
        safe_record.exc_info = None
        safe_record.exc_text = None
        return super().format(safe_record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
