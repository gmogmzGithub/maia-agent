"""Versioned client for the pinned Hermes Runtime (ADR-0008, P-032).

The Product Worker talks to a *separately running* ``hermes serve`` through its
authenticated local JSON-RPC WebSocket. This module is the only place in the
product that knows the Hermes wire contract. Nothing here imports ``AIAgent``,
the gateway runner, or any other Hermes internal.

Checkpoint 0 uses only the health and capability portion of the contract. The
conversational methods are probed for existence but never invoked for effect.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus, WebSocketException

logger = logging.getLogger(__name__)

# The JSON-RPC methods the product depends on. ADR-0008 pins both the Hermes
# version and this capability contract; a runtime missing any of them cannot
# run the product's conversation or in-flight reconciliation behavior.
REQUIRED_METHODS: tuple[str, ...] = (
    "session.create",
    "session.resume",
    "session.status",
    "session.list",
    "prompt.submit",
    "session.steer",
    "session.redirect",
    "session.interrupt",
)

# Probing a session-scoped method with an id that cannot exist is side-effect
# free: the runtime resolves the session first and rejects with "session not
# found" before doing anything. An unknown *method* answers -32601 instead,
# which is how a missing capability is distinguished from a present one.
_PROBE_SESSION_ID = "realestate-capability-probe-nonexistent"
_JSONRPC_METHOD_NOT_FOUND = -32601


class HermesStatus(str, Enum):
    """Outcome of a runtime health check, in operator-actionable terms."""

    OK = "ok"
    UNREACHABLE = "unreachable"
    UNAUTHENTICATED = "unauthenticated"
    INCOMPATIBLE = "incompatible"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(frozen=True)
class HermesHealth:
    status: HermesStatus
    detail: str
    version: str | None = None
    pinned_version: str | None = None
    missing_methods: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status is HermesStatus.OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail,
            "version": self.version,
            "pinned_version": self.pinned_version,
            "missing_methods": list(self.missing_methods),
        }


class HermesUnavailable(RuntimeError):
    """Raised when a required Hermes call cannot be made."""

    def __init__(self, health: HermesHealth) -> None:
        super().__init__(f"{health.status.value}: {health.detail}")
        self.health = health


class HermesClient:
    """Thin JSON-RPC client over the authenticated local WebSocket."""

    def __init__(
        self,
        base_url: str,
        session_token: str,
        pinned_version: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = session_token
        self._pinned_version = pinned_version
        self._timeout = timeout_seconds
        self._http: httpx.AsyncClient | None = None
        logger.debug(
            "HermesClient configured (base_url=%s, pinned_version=%s, timeout=%.2fs)",
            self._base_url,
            self._pinned_version,
            self._timeout,
        )

    def _client(self) -> httpx.AsyncClient:
        """The process-lifetime client, created on first use.

        The liveness probe runs on every ``/health``, every ``/health/hermes``
        and each startup report, so a client per probe would mean a fresh TCP
        handshake per operator poll — the same reason the WhatsApp and Telegram
        clients hold one pool.
        """
        if self._http is None:
            logger.debug("Opening HTTP client pool for Hermes health checks")
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            logger.debug("Closing HTTP client pool for Hermes health checks")
            await self._http.aclose()
            self._http = None

    @classmethod
    def from_settings(cls, settings: Any) -> "HermesClient":
        """Build the client the way the application and the local scripts do.

        One factory so a new transport setting reaches every entry point rather
        than only the ones someone remembered to update.
        """
        return cls(
            base_url=settings.hermes_base_url,
            session_token=settings.hermes_session_token,
            pinned_version=settings.hermes_pinned_version,
            timeout_seconds=settings.hermes_timeout_seconds,
        )

    # -- URLs ------------------------------------------------------------

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self._base_url.startswith("https://") else "ws"
        netloc = self._base_url.split("://", 1)[1]
        return f"{scheme}://{netloc}/api/ws?{urlencode({'token': self._token})}"

    @property
    def health_url(self) -> str:
        return f"{self._base_url}/api/health"

    # -- Health ----------------------------------------------------------

    async def check_health(self) -> HermesHealth:
        """Verify the runtime is reachable, pinned, authenticated, and capable.

        Returns a structured result instead of raising so callers (the health
        endpoint, the startup banner) can report the precise reason a Stage 0
        operator needs in order to fix it.
        """
        if not self._token:
            logger.error("Hermes health check cannot authenticate: token is missing")
            return HermesHealth(
                status=HermesStatus.UNAUTHENTICATED,
                detail=(
                    "HERMES_DASHBOARD_SESSION_TOKEN is not set. Add the shared "
                    "token to .env and recreate the Compose services."
                ),
                pinned_version=self._pinned_version,
            )

        try:
            logger.debug("Checking Hermes process health at %s", self.health_url)
            process = await self._check_process()
            if process.status is not HermesStatus.OK:
                logger.warning(
                    "Hermes process health failed (status=%s, detail=%s)",
                    process.status.value,
                    process.detail,
                )
                return process
            capabilities = await self._check_capabilities(version=process.version)
            if capabilities.ok:
                logger.info(
                    "Hermes runtime ready (version=%s, required_methods=%d)",
                    capabilities.version,
                    len(REQUIRED_METHODS),
                )
            else:
                logger.warning(
                    "Hermes capability check failed (status=%s, missing=%s)",
                    capabilities.status.value,
                    ",".join(capabilities.missing_methods) or "none",
                )
            return capabilities
        except Exception as exc:
            # The health surface must always answer. An unexpected fault here is
            # itself the report, not a crash.
            logger.exception("Unexpected Hermes health-check failure")
            return HermesHealth(
                status=HermesStatus.PROTOCOL_ERROR,
                detail=f"Hermes health check failed: {exc.__class__.__name__}: {exc}",
                pinned_version=self._pinned_version,
            )

    async def _check_process(self) -> HermesHealth:
        """HTTP liveness plus the pinned-version comparison."""
        try:
            response = await self._client().get(self.health_url)
        except httpx.HTTPError as exc:
            logger.warning("Hermes health HTTP request failed (%s)", exc.__class__.__name__)
            return HermesHealth(
                status=HermesStatus.UNREACHABLE,
                detail=(
                    f"No Hermes Runtime answered {self.health_url} ({exc.__class__.__name__}). "
                    "Start it with `docker compose up hermes`."
                ),
                pinned_version=self._pinned_version,
            )

        if response.status_code != 200:
            logger.warning(
                "Hermes health endpoint returned HTTP %d", response.status_code
            )
            return HermesHealth(
                status=HermesStatus.UNREACHABLE,
                detail=f"{self.health_url} returned HTTP {response.status_code}.",
                pinned_version=self._pinned_version,
            )

        try:
            payload = response.json()
        except ValueError:
            logger.error("Hermes health endpoint returned non-JSON")
            return HermesHealth(
                status=HermesStatus.PROTOCOL_ERROR,
                detail=f"{self.health_url} did not return JSON.",
                pinned_version=self._pinned_version,
            )

        version = payload.get("version")
        logger.debug(
            "Hermes health payload received (version=%r, auth_required=%r)",
            version,
            payload.get("auth_required"),
        )
        if version != self._pinned_version:
            logger.error(
                "Hermes version mismatch (reported=%r, pinned=%r)",
                version,
                self._pinned_version,
            )
            return HermesHealth(
                status=HermesStatus.INCOMPATIBLE,
                detail=(
                    f"Hermes reports version {version!r} but the product is pinned to "
                    f"{self._pinned_version!r}. Re-pin HERMES_PINNED_VERSION only after "
                    "re-verifying the JSON-RPC capability contract."
                ),
                version=version,
                pinned_version=self._pinned_version,
            )

        if payload.get("auth_required"):
            logger.error("Hermes is running with dashboard auth gate enabled")
            return HermesHealth(
                status=HermesStatus.UNAUTHENTICATED,
                detail=(
                    "Hermes is running in gated dashboard-auth mode, which rejects the "
                    "loopback token the product uses. Stage 0 expects a local "
                    "`hermes serve` without the auth gate."
                ),
                version=version,
                pinned_version=self._pinned_version,
            )

        return HermesHealth(
            status=HermesStatus.OK,
            detail="process reachable",
            version=version,
            pinned_version=self._pinned_version,
        )

    async def _check_capabilities(self, version: str | None) -> HermesHealth:
        """Open the authenticated WebSocket and probe the pinned method set."""
        try:
            logger.debug(
                "Opening Hermes JSON-RPC WebSocket for capability probe (%d methods)",
                len(REQUIRED_METHODS),
            )
            async with self.session() as rpc:
                missing = [
                    name
                    for name in REQUIRED_METHODS
                    if not await rpc.method_exists(name)
                ]
        except HermesUnavailable as exc:
            return exc.health

        if missing:
            logger.error("Hermes missing required JSON-RPC methods: %s", ", ".join(missing))
            return HermesHealth(
                status=HermesStatus.INCOMPATIBLE,
                detail=(
                    "The Hermes JSON-RPC surface is missing methods the product "
                    f"requires: {', '.join(missing)}."
                ),
                version=version,
                pinned_version=self._pinned_version,
                missing_methods=tuple(missing),
            )

        return HermesHealth(
            status=HermesStatus.OK,
            detail=(
                f"Hermes {version} reachable, authenticated, and exposing all "
                f"{len(REQUIRED_METHODS)} required JSON-RPC methods."
            ),
            version=version,
            pinned_version=self._pinned_version,
        )

    # -- Connection ------------------------------------------------------

    def session(self) -> "_HermesConnection":
        return _HermesConnection(self)


class _HermesConnection:
    """One authenticated JSON-RPC WebSocket, used as an async context manager."""

    def __init__(self, client: HermesClient) -> None:
        self._client = client
        self._ws: Any = None
        self._next_id = 0

    async def __aenter__(self) -> "_HermesConnection":
        try:
            logger.debug("Opening Hermes JSON-RPC WebSocket")
            self._ws = await asyncio.wait_for(
                ws_connect(self._client.ws_url, open_timeout=self._client._timeout),
                timeout=self._client._timeout,
            )
        except InvalidStatus as exc:
            logger.error(
                "Hermes WebSocket upgrade refused (http_status=%d)",
                exc.response.status_code,
            )
            raise HermesUnavailable(
                HermesHealth(
                    status=HermesStatus.UNAUTHENTICATED,
                    detail=(
                        "Hermes refused the JSON-RPC WebSocket upgrade "
                        f"(HTTP {exc.response.status_code}). Check that "
                        "HERMES_DASHBOARD_SESSION_TOKEN matches the running runtime."
                    ),
                    pinned_version=self._client._pinned_version,
                )
            ) from exc
        except (WebSocketException, OSError, asyncio.TimeoutError) as exc:
            logger.warning("Hermes WebSocket open failed (%s)", exc.__class__.__name__)
            raise HermesUnavailable(
                HermesHealth(
                    status=HermesStatus.UNREACHABLE,
                    detail=(
                        f"Could not open the Hermes JSON-RPC WebSocket "
                        f"({exc.__class__.__name__})."
                    ),
                    pinned_version=self._client._pinned_version,
                )
            ) from exc

        # The runtime closes the socket with code 4401 when the credential is
        # rejected after accept, so an immediate close is an auth failure rather
        # than a transport fault.
        try:
            await self._await_ready()
        except HermesUnavailable:
            await self.close()
            raise
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                logger.debug("Closing Hermes JSON-RPC WebSocket")
                await self._ws.close()
            finally:
                self._ws = None

    async def _await_ready(self) -> None:
        """Consume frames until the runtime's ``gateway.ready`` event arrives."""
        deadline = self._client._timeout
        while True:
            frame = await self._receive(timeout=deadline)
            params = frame.get("params")
            if frame.get("method") == "event" and isinstance(params, dict):
                if params.get("type") == "gateway.ready":
                    logger.debug("Hermes JSON-RPC gateway.ready received")
                    return

    async def _receive(self, timeout: float) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HermesUnavailable(
                HermesHealth(
                    status=HermesStatus.PROTOCOL_ERROR,
                    detail="Hermes accepted the WebSocket but sent no response in time.",
                    pinned_version=self._client._pinned_version,
                )
            ) from exc
        except WebSocketException as exc:
            code = getattr(self._ws, "close_code", None)
            status = (
                HermesStatus.UNAUTHENTICATED
                if code in (4401, 4403)
                else HermesStatus.UNREACHABLE
            )
            raise HermesUnavailable(
                HermesHealth(
                    status=status,
                    detail=(
                        f"Hermes closed the JSON-RPC WebSocket (code={code}). "
                        "A 4401/4403 close means the local token was rejected."
                    ),
                    pinned_version=self._client._pinned_version,
                )
            ) from exc

        try:
            frame = json.loads(raw)
            if isinstance(frame, dict):
                logger.debug(
                    "Hermes JSON-RPC frame received "
                    "(id=%r, method=%r, has_result=%s, has_error=%s)",
                    frame.get("id"),
                    frame.get("method"),
                    "result" in frame,
                    "error" in frame,
                )
            return frame
        except (TypeError, ValueError) as exc:
            raise HermesUnavailable(
                HermesHealth(
                    status=HermesStatus.PROTOCOL_ERROR,
                    detail="Hermes sent a frame that is not JSON-RPC.",
                    pinned_version=self._client._pinned_version,
                )
            ) from exc

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one JSON-RPC request and return its raw response frame.

        Events interleaved before the matching response are skipped; the caller
        gets the frame whose ``id`` matches the request.
        """
        self._next_id += 1
        request_id = self._next_id
        safe_params = dict(params or {})
        if "text" in safe_params:
            safe_params["text"] = f"<{len(str(safe_params['text']))} chars>"
        logger.debug(
            "Hermes JSON-RPC call -> %s (id=%s, params=%s)",
            method,
            request_id,
            safe_params,
        )
        await self._ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
        )
        while True:
            frame = await self._receive(timeout=self._client._timeout)
            if frame.get("id") == request_id:
                if frame.get("error"):
                    logger.warning(
                        "Hermes JSON-RPC call <- %s (id=%s, error=%s)",
                        method,
                        request_id,
                        frame.get("error"),
                    )
                else:
                    logger.debug(
                        "Hermes JSON-RPC call <- %s (id=%s, ok)", method, request_id
                    )
                return frame

    async def receive_event_or_none(self, timeout: float) -> dict[str, Any] | None:
        """Poll for an event, returning None if none arrives within *timeout*.

        A quiet socket is a normal outcome, which is what lets a caller
        interleave other work — adopting newly arrived messages — while a model
        turn is still running.
        """
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except WebSocketException as exc:
            raise HermesUnavailable(
                HermesHealth(
                    status=HermesStatus.UNREACHABLE,
                    detail=f"Hermes closed the WebSocket mid-turn: {exc}",
                    pinned_version=self._client._pinned_version,
                )
            ) from exc

        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("Ignored non-JSON frame while waiting for Hermes event")
            return None
        if frame.get("method") == "event" and isinstance(frame.get("params"), dict):
            params = frame["params"]
            payload = params.get("payload") if isinstance(params, dict) else None
            logger.debug(
                "Hermes event received (type=%r, session_id=%r, tool=%r, status=%r)",
                params.get("type"),
                params.get("session_id"),
                (payload or {}).get("name") if isinstance(payload, dict) else None,
                (payload or {}).get("status") if isinstance(payload, dict) else None,
            )
            return frame["params"]
        logger.debug("Ignored non-event Hermes frame while polling (keys=%s)", list(frame))
        return None

    async def method_exists(self, method: str) -> bool:
        """True when the runtime recognises *method*.

        The probe uses a session id that cannot exist, so a present method
        rejects with "session not found" rather than performing any work.
        """
        frame = await self.call(method, {"session_id": _PROBE_SESSION_ID})
        error = frame.get("error")
        if isinstance(error, dict) and error.get("code") == _JSONRPC_METHOD_NOT_FOUND:
            return False
        return True
