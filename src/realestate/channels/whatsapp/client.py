"""Outbound delivery through the official Meta Cloud API (P-021).

The Product Outbox sends directly against Meta rather than through Hermes's
channel adapter, which is what lets Stage 0 own durability and, later, approved
template sends without forking Hermes (TC-004, ADR-0003).

The single most important behaviour here is the three-way outcome. Meta's
answer is classified as:

* **sent** — conclusive success, with the provider message id;
* **failed** — a conclusive rejection, marked retryable or permanent;
* **unknown** — the request may have been accepted but no conclusive result
  came back. It is never replayed automatically, because the POC prefers a
  missing reply to a duplicate one (P-036).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import httpx


class SendOutcome(str, Enum):
    SENT = "sent"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    provider_message_id: str | None = None
    detail: str = ""
    retry_after_seconds: float | None = None

    @property
    def conclusive(self) -> bool:
        return self.outcome is not SendOutcome.UNKNOWN


# Meta HTTP statuses that mean "this will never succeed as-is". Authentication,
# authorization, validation, and payload faults are not retried (P-036).
_PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 413, 414, 422})

# How long an idle pooled connection may be reused. See _client().
KEEPALIVE_EXPIRY_SECONDS = 15.0


def normalize_recipient(wa_id: str) -> str:
    """Return the form Meta accepts as a send target.

    Mexican mobile numbers carry a legacy ``1`` after the country code. Meta
    reports inbound senders as ``521XXXXXXXXXX`` but rejects that same string as
    a send target on the test number's allowlist, which stores
    ``52XXXXXXXXXX``. Observed directly: replying to the exact ``wa_id`` Meta
    gave us failed with ``131030 Recipient phone number not in allowed list``,
    while the un-prefixed form delivered.

    Only ``521`` + 10 digits is touched. Everything else is returned unchanged,
    so this cannot silently mangle another country's numbering.
    """
    digits = "".join(c for c in wa_id if c.isdigit())
    if len(digits) == 13 and digits.startswith("521"):
        return "52" + digits[3:]
    return digits or wa_id


class WhatsAppClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        graph_version: str = "v25.0",
        base_url: str = "https://graph.facebook.com",
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = access_token
        self._phone_number_id = phone_number_id
        self._base_url = base_url.rstrip("/")
        self._graph_version = graph_version
        self._base = f"{self._base_url}/{graph_version}/{phone_number_id}"
        self._timeout = timeout_seconds
        # Only tests pass a transport; it lets them drive the real client, so the
        # credential header and the status classification are actually covered.
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self._token and self._phone_number_id)

    def _client(self) -> httpx.AsyncClient:
        """The process-lifetime client, created on first use.

        One connection pool for every outbound message: a client per send would
        pay a TCP and TLS handshake to Meta on each Lead reply.

        ``keepalive_expiry`` is deliberately short. Sending on a pooled socket
        that Meta has already closed raises ``RemoteProtocolError``, which
        :meth:`_post` must classify as inconclusive — never retried, because it
        cannot tell that case from a fault after Meta accepted the message. The
        Outbox drains at most once per second, so dropping idle connections well
        inside Meta's own timeout keeps that ambiguity out of the send path while
        still reusing the connection across a burst.
        """
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._token}"},
                limits=httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS),
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def check_health(self) -> dict[str, object]:
        """Report whether Meta will accept this token, and for how long.

        Stage 0 runs on 24-hour test-number tokens, so an expiry mid-session is
        expected rather than exceptional. Surfacing it here turns what would
        otherwise be a run of opaque Outbox failures into an obvious cause.
        """
        if not self.configured:
            return {
                "status": "unconfigured",
                "detail": "META_ACCESS_TOKEN / META_PHONE_NUMBER_ID are not set.",
            }

        url = f"{self._base_url}/{self._graph_version}/debug_token"
        try:
            response = await self._client().get(url, params={"input_token": self._token})
            body = response.json()
            # Meta, or a proxy standing in for it, may answer with a non-object
            # body. A health probe reports that; it never raises, because it is
            # gathered with the others and an escape would take down /health.
            payload = (body.get("data") or {}) if isinstance(body, dict) else {}
        except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
            return {
                "status": "unknown",
                "detail": f"Could not reach Meta to check the token ({exc.__class__.__name__}).",
            }

        if not payload.get("is_valid"):
            return {
                "status": "invalid",
                "detail": (
                    "Meta rejected META_ACCESS_TOKEN. Generate a new one on the app's "
                    "API Setup page and run scripts/set-meta-token.sh."
                ),
            }

        expires_at = payload.get("expires_at")
        if expires_at in (0, None):
            return {"status": "ok", "detail": "token valid, no expiry"}

        expiry = datetime.fromtimestamp(int(expires_at), tz=UTC)
        hours = (expiry - datetime.now(tz=UTC)).total_seconds() / 3600
        if hours <= 0:
            return {
                "status": "expired",
                "detail": (
                    f"META_ACCESS_TOKEN expired at {expiry.isoformat()}. "
                    "Run scripts/set-meta-token.sh with a fresh one."
                ),
            }
        return {
            "status": "ok" if hours >= 1 else "expiring",
            "detail": f"token valid until {expiry.isoformat()} ({hours:.1f}h left)",
            "expires_at": expiry.isoformat(),
        }

    async def send_text(self, to_wa_id: str, body: str) -> SendResult:
        """Send one free-form text message inside the customer-service window."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalize_recipient(to_wa_id),
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return await self._post("/messages", payload)

    async def _post(self, path: str, payload: dict) -> SendResult:
        if not self.configured:
            return SendResult(
                outcome=SendOutcome.FAILED_PERMANENT,
                detail="META_ACCESS_TOKEN / META_PHONE_NUMBER_ID are not configured.",
            )

        try:
            response = await self._client().post(f"{self._base}{path}", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The request never reached Meta, so retrying cannot duplicate it.
            return SendResult(
                outcome=SendOutcome.FAILED_RETRYABLE,
                detail=f"could not reach Meta: {exc.__class__.__name__}",
            )
        except httpx.HTTPError as exc:
            # A read timeout or transport fault *after* the request went out:
            # Meta may already have accepted it. Not conclusive, not replayed.
            return SendResult(
                outcome=SendOutcome.UNKNOWN,
                detail=f"no conclusive result from Meta: {exc.__class__.__name__}",
            )

        return self._classify(response)

    def _classify(self, response: httpx.Response) -> SendResult:
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                # Meta answered 200 but unreadably: the send probably happened.
                return SendResult(
                    outcome=SendOutcome.UNKNOWN,
                    detail="Meta returned 200 with an unreadable body.",
                )
            messages = body.get("messages") if isinstance(body, dict) else None
            first = messages[0] if isinstance(messages, list) and messages else None
            provider_id = first.get("id") if isinstance(first, dict) else None
            if not provider_id:
                return SendResult(
                    outcome=SendOutcome.UNKNOWN,
                    detail="Meta returned 200 without a message id.",
                )
            return SendResult(
                outcome=SendOutcome.SENT, provider_message_id=str(provider_id)
            )

        detail = self._error_detail(response)

        # Only an explicitly permanent status stops the retry curve. Everything
        # else — 429, 5xx, and anything unrecognised — is worth another attempt.
        if response.status_code in _PERMANENT_STATUSES:
            return SendResult(outcome=SendOutcome.FAILED_PERMANENT, detail=detail)
        return SendResult(
            outcome=SendOutcome.FAILED_RETRYABLE,
            detail=detail,
            retry_after_seconds=self._retry_after(response),
        )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict):
            error = {}
        message = error.get("message") or response.text[:200]
        code = error.get("code")
        return f"HTTP {response.status_code}" + (
            f" code={code}: {message}" if code else f": {message}"
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        """A Meta ``Retry-After`` instruction overrides the fixed delays (P-036)."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
