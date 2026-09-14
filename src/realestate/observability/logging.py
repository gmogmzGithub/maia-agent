"""Structured logs with a deliberately conservative privacy backstop."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any


_PHONE = re.compile(r"(?<![\w])\+?\d(?:[\s.-]?\d){6,14}(?![\w])")
_URL = re.compile(r"https?://[^\s'\"]+")
_SECRET = re.compile(
    r"(?i)\b(authorization|bearer|token|api[_-]?key|access[_-]?token)\b"
    r"([:=\s]+)(?:bearer\s+)?([^\s,}\]]+)"
)


def redact(value: str) -> str:
    """Remove common accidental identifiers from a legacy log message.

    The event envelope remains the primary boundary: only allowlisted fields
    enter new telemetry. This filter protects legacy logs and third-party
    libraries from the common classes of accidental leakage while migration is
    ongoing; it is intentionally not treated as authorization to log content.
    """
    value = _URL.sub("<redacted-url>", value)
    value = _SECRET.sub(r"\1\2<redacted>", value)
    return _PHONE.sub("<redacted-number>", value)


class PrivacyFilter(logging.Filter):
    """Strip exception text and redact the formatted legacy record in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            # Uvicorn's AccessFormatter unpacks this exact five-value tuple.
            # Preserve its contract while dropping the client address and query
            # string before that formatter ever sees them.
            try:
                _client, method, path, version, status_code = record.args
            except ValueError:
                pass
            else:
                safe_path = str(path).split("?", 1)[0]
                # Docker's liveness probe calls this endpoint continuously.
                # A successful probe is not an operator event; preserving it
                # would bury the lifecycle and failure evidence this logger is
                # for. Failed probes remain visible.
                successful_status = str(status_code).startswith(("1", "2", "3"))
                if method == "GET" and safe_path == "/live" and successful_status:
                    return False
                record.args = ("<redacted-client>", method, safe_path, version, status_code)
                return True
        exception_type: str | None = None
        if record.exc_info is not None and record.exc_info[0] is not None:
            exception_type = record.exc_info[0].__name__
        try:
            message = record.getMessage()
        except Exception:
            message = "<unrenderable log message>"
        record.msg = redact(message)
        record.args = ()
        if exception_type is not None:
            record.msg = f"{record.msg} (exception_type={exception_type})"
            # Tracebacks commonly embed request bodies and provider responses.
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, suitable for Docker logs and future shipping."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
        }
        if message.startswith("telemetry "):
            try:
                telemetry = json.loads(message.removeprefix("telemetry "))
            except json.JSONDecodeError:
                payload["message"] = "<invalid telemetry event>"
            else:
                payload.update(telemetry)
        else:
            payload["message"] = message
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_product_logging(level: int) -> None:
    """Install the one safe formatter/filter pair without duplicating handlers."""
    privacy = PrivacyFilter()
    product = logging.getLogger("realestate")
    if not product.handlers:
        product_handler = logging.StreamHandler()
        product.addHandler(product_handler)
        product.propagate = False
    for configured_handler in product.handlers:
        configured_handler.addFilter(privacy)
        configured_handler.setFormatter(JsonFormatter())
    product.setLevel(level)

    # Uvicorn's access logger is outside ``realestate`` and otherwise exposes
    # full paths and query strings. Keep its handler/format conventions but
    # ensure it sees the same privacy filter before formatting.
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.addFilter(privacy)
        for configured_handler in logger.handlers:
            configured_handler.addFilter(privacy)
