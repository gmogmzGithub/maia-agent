"""The private Telegram Administrative Channel (P-040).

Long polling rather than a webhook: it needs no second public route, no extra
tunnel path, and no signature scheme, which keeps the Stage 0 topology at the
four accepted pieces. Telegram's ``offset`` gives at-least-once delivery, so the
product persists a cursor and deduplicates on ``update_id``.

Lead conversations never reach this channel, and administrative commands are
never accepted from the Lead-facing WhatsApp number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    chat_id: str
    from_user_id: str
    from_username: str | None
    text: str | None
    sent_at: datetime
    raw: dict[str, Any] = field(repr=False)


def parse_updates(payload: Any) -> list[TelegramUpdate]:
    """Extract the plain text messages from a ``getUpdates`` response.

    Edits, channel posts, callbacks, and non-text messages are ignored: Stage 0
    administration is a natural-language conversation, not a button UI.
    """
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if not isinstance(result, list):
        return []

    updates: list[TelegramUpdate] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        chat_id = chat.get("id")
        sender_id = sender.get("id")
        try:
            update_id = int(item["update_id"])
            sent_at = datetime.fromtimestamp(
                int(message.get("date") or 0)
                or int(datetime.now(tz=UTC).timestamp()),
                tz=UTC,
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            # Provider input is untrusted. One malformed update must not make
            # the poller discard the other valid updates in the same response.
            #
            # OSError belongs here: a timestamp far past the platform's range
            # (1e18) raises OSError rather than OverflowError, and get_updates
            # only catches HTTPError and ValueError — so it would have escaped
            # the poller and failed the whole background tick.
            continue
        if chat_id is None or sender_id is None:
            continue
        updates.append(
            TelegramUpdate(
                update_id=update_id,
                chat_id=str(chat_id),
                from_user_id=str(sender_id),
                from_username=sender.get("username"),
                text=message.get("text"),
                sent_at=sent_at,
                raw=item,
            )
        )
    return updates


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        base_url: str = "https://api.telegram.org",
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = bot_token
        self._base = f"{base_url.rstrip('/')}/bot{bot_token}"
        self._timeout = timeout_seconds
        # Only tests pass a transport; it lets them drive the real client.
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _client(self) -> httpx.AsyncClient:
        """The process-lifetime client, created on first use.

        ``get_updates`` runs on every background-loop iteration, so a client per
        call would mean a TCP and TLS handshake to Telegram every poll.
        """
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def get_updates(self, offset: int, limit: int = 20) -> list[TelegramUpdate]:
        """Fetch pending updates from *offset*. Returns [] on any failure.

        Deliberately non-raising: a transient Telegram outage must not take down
        the background loop that also serves WhatsApp.
        """
        if not self.configured:
            return []
        try:
            response = await self._client().get(
                f"{self._base}/getUpdates",
                params={"offset": offset, "limit": limit, "timeout": 0},
            )
            if response.status_code != 200:
                return []
            return parse_updates(response.json())
        except (httpx.HTTPError, ValueError):
            return []

    async def send_message(self, chat_id: str, text: str) -> bool:
        if not self.configured:
            return False
        try:
            response = await self._client().post(
                f"{self._base}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def check_health(self) -> dict[str, object]:
        if not self.configured:
            return {"status": "unconfigured", "detail": "TELEGRAM_BOT_TOKEN is not set."}
        try:
            response = await self._client().get(f"{self._base}/getMe")
            body = response.json()
            if not isinstance(body, dict):
                # A non-object body is a misbehaving intermediary, not a verdict
                # on the token. A probe reports that; it never raises, because it
                # is gathered with the others and an escape would fail /health.
                raise TypeError("getMe returned a non-object body")
        except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
            return {
                "status": "unknown",
                "detail": f"Could not reach Telegram ({exc.__class__.__name__}).",
            }
        if not body.get("ok"):
            return {"status": "invalid", "detail": "Telegram rejected TELEGRAM_BOT_TOKEN."}
        bot = body.get("result") or {}
        return {"status": "ok", "detail": f"bot @{bot.get('username')} reachable"}
