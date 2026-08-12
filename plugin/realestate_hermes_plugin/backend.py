"""HTTP client for the Product application.

The plugin is a thin typed adapter (ADR-0009). It owns no business rules, opens
no database connection, and holds no Google Calendar credential. Every call
authenticates with the shared local plugin token and forwards the Hermes-supplied
trusted ``session_id`` / ``task_id`` so the Product application resolves actor and
Conversation identity itself, never accepting them as model-generated authority.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

SESSION_HEADER = "X-Hermes-Session-Id"
TASK_HEADER = "X-Hermes-Task-Id"

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT_SECONDS = 15.0
logger = logging.getLogger(__name__)


class BackendNotConfigured(RuntimeError):
    """The plugin is loaded but has no credential for the Product application."""


@dataclass(frozen=True)
class BackendConfig:
    base_url: str
    token: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "BackendConfig":
        token = os.environ.get("REALESTATE_PLUGIN_API_TOKEN", "").strip()
        if not token:
            raise BackendNotConfigured(
                "REALESTATE_PLUGIN_API_TOKEN is not set in the Hermes Runtime "
                "environment. The plugin cannot reach the Product application."
            )
        return cls(
            base_url=os.environ.get("REALESTATE_BACKEND_URL", DEFAULT_BASE_URL).rstrip("/"),
            token=token,
            timeout_seconds=float(
                os.environ.get("REALESTATE_BACKEND_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
            ),
        )


def call_backend(
    method: str,
    path: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
    json_body: dict[str, Any] | None = None,
    config: BackendConfig | None = None,
) -> dict[str, Any]:
    """Perform one authenticated request and return the decoded JSON body.

    Transport and protocol problems are returned as a structured
    ``temporarily_unavailable`` result rather than raised, so a caller inside the
    Hermes tool loop never sees an exception escape.
    """
    try:
        resolved = config or BackendConfig.from_env()
    except BackendNotConfigured as exc:
        logger.error("Plugin backend is not configured: %s", exc)
        return {"result": "temporarily_unavailable", "detail": str(exc)}

    headers = {"Authorization": f"Bearer {resolved.token}"}
    if session_id:
        headers[SESSION_HEADER] = session_id
    if task_id:
        headers[TASK_HEADER] = task_id

    logger.debug(
        "Plugin -> Product request "
        "(method=%s, path=%s, base_url=%s, session=%s, task=%s, body_keys=%s)",
        method,
        path,
        resolved.base_url,
        session_id or "<none>",
        task_id or "<none>",
        sorted((json_body or {}).keys()),
    )
    try:
        response = httpx.request(
            method,
            f"{resolved.base_url}{path}",
            headers=headers,
            json=json_body,
            timeout=resolved.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Plugin -> Product request failed (method=%s, path=%s, error=%s)",
            method,
            path,
            exc.__class__.__name__,
        )
        return {
            "result": "temporarily_unavailable",
            "detail": (
                f"The Product application at {resolved.base_url} is not reachable "
                f"({exc.__class__.__name__})."
            ),
        }

    if response.status_code == 401:
        logger.warning("Plugin credential rejected by Product application (path=%s)", path)
        return {
            "result": "forbidden",
            "detail": "The Product application rejected the plugin credential.",
        }
    if response.status_code >= 400:
        logger.warning(
            "Product application returned an error to plugin (path=%s, status=%d)",
            path,
            response.status_code,
        )
        return {
            "result": "temporarily_unavailable",
            "detail": f"The Product application returned HTTP {response.status_code}.",
        }

    try:
        payload = response.json()
    except ValueError:
        logger.error("Product application returned non-JSON to plugin (path=%s)", path)
        return {
            "result": "temporarily_unavailable",
            "detail": "The Product application returned a non-JSON body.",
        }
    if not isinstance(payload, dict):
        logger.error("Product application returned unexpected JSON shape to plugin (path=%s)", path)
        return {
            "result": "temporarily_unavailable",
            "detail": "The Product application returned an unexpected JSON shape.",
        }
    logger.debug(
        "Plugin <- Product response (path=%s, status=%d, result=%s, keys=%s)",
        path,
        response.status_code,
        payload.get("result"),
        sorted(payload.keys()),
    )
    return payload


def check_backend(
    *,
    session_id: str | None = None,
    task_id: str | None = None,
    config: BackendConfig | None = None,
) -> dict[str, Any]:
    """Checkpoint 0 health call: prove the plugin can reach the Product application."""
    return call_backend(
        "GET",
        "/internal/plugin/health",
        session_id=session_id,
        task_id=task_id,
        config=config,
    )
