"""Parse Facebook Page Messenger webhook events into Product messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from realestate.channels.messaging import CustomerChannel, InboundMessage


def _timestamp(value: Any) -> datetime:
    try:
        # Messenger timestamps are milliseconds since the Unix epoch.
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(tz=UTC)


def parse_webhook(body: dict[str, Any]) -> list[InboundMessage]:
    """Return identifiable inbound messages; ignore unrelated Meta events."""
    if body.get("object") != "page":
        return []

    parsed: list[InboundMessage] = []
    for entry in body.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        entry_account_id = str(entry.get("id") or "")
        for event in entry.get("messaging") or []:
            if not isinstance(event, dict):
                continue
            message = event.get("message")
            if not isinstance(message, dict) or message.get("is_echo") is True:
                continue
            sender = event.get("sender")
            recipient = event.get("recipient")
            sender_id = sender.get("id") if isinstance(sender, dict) else None
            account_id = (
                recipient.get("id") if isinstance(recipient, dict) else None
            ) or entry_account_id
            message_id = message.get("mid")
            if not sender_id or not account_id or not message_id:
                continue
            text = message.get("text")
            parsed.append(
                InboundMessage(
                    channel=CustomerChannel.FACEBOOK_MESSENGER,
                    provider_message_id=str(message_id),
                    sender_id=str(sender_id),
                    channel_account_id=str(account_id),
                    message_type="text" if isinstance(text, str) else "attachment",
                    sent_at=_timestamp(event.get("timestamp")),
                    text=text if isinstance(text, str) else None,
                    profile_name=None,
                    raw=event,
                )
            )
    return parsed
