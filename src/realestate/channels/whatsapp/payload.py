"""Parsing the Meta WhatsApp Cloud API webhook body.

Deliberately tolerant. Meta adds fields, sends message types the POC does not
handle, and batches several entries into one request. Anything unrecognised is
skipped rather than treated as an error, because rejecting the payload would
make Meta retry a body that will never parse.

The complete authenticated message object is carried through untouched so the
Inbox can retain it. Stage 0 does not assume a Click-to-WhatsApp reference
exists or where it lives; ``referral`` is surfaced only for inspection, and no
mapping to a Property is derived from it until V-001 proves the field (P-049).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from realestate.channels.messaging import CustomerChannel


@dataclass(frozen=True)
class InboundMessage:
    wamid: str
    from_wa_id: str
    phone_number_id: str
    message_type: str
    sent_at: datetime
    text: str | None
    profile_name: str | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def channel(self) -> CustomerChannel:
        return CustomerChannel.WHATSAPP

    @property
    def provider_message_id(self) -> str:
        return self.wamid

    @property
    def sender_id(self) -> str:
        return self.from_wa_id

    @property
    def channel_account_id(self) -> str:
        return self.phone_number_id

    @property
    def referral(self) -> dict[str, Any] | None:
        """Advertisement metadata, when Meta supplies it. Unproven — see V-001."""
        value = self.raw.get("referral")
        return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class DeliveryUpdate:
    provider_message_id: str
    status: str
    occurred_at: datetime
    recipient_wa_id: str | None
    #: The number the callback arrived on. Present since Stage 9 because it is
    #: how Product decides which Brokerage Organization's Outbox row a delivery
    #: result belongs to (ADR-0050). Meta reports it in the same ``metadata``
    #: block as for an inbound message, so no extra parsing is needed.
    phone_number_id: str = ""
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class ParsedWebhook:
    messages: list[InboundMessage]
    statuses: list[DeliveryUpdate]


def _timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)


def _text_of(message: dict[str, Any]) -> str | None:
    """Extract human text from the message shapes Stage 0 can act on."""
    message_type = message.get("type")
    if message_type == "text":
        body = (message.get("text") or {}).get("body")
        return body if isinstance(body, str) else None
    if message_type == "button":
        return (message.get("button") or {}).get("text")
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        for key in ("button_reply", "list_reply"):
            if isinstance(interactive.get(key), dict):
                title = interactive[key].get("title")
                return title if isinstance(title, str) else None
    return None


def parse_webhook(body: dict[str, Any]) -> ParsedWebhook:
    messages: list[InboundMessage] = []
    statuses: list[DeliveryUpdate] = []

    for entry in body.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            names = {
                contact.get("wa_id"): (contact.get("profile") or {}).get("name")
                for contact in value.get("contacts") or []
                if isinstance(contact, dict)
            }

            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                wamid = message.get("id")
                sender = message.get("from")
                if not wamid or not sender:
                    continue
                messages.append(
                    InboundMessage(
                        wamid=str(wamid),
                        from_wa_id=str(sender),
                        phone_number_id=phone_number_id,
                        message_type=str(message.get("type") or "unknown"),
                        sent_at=_timestamp(message.get("timestamp")),
                        text=_text_of(message),
                        profile_name=names.get(sender),
                        raw=message,
                    )
                )

            for status in value.get("statuses") or []:
                if not isinstance(status, dict):
                    continue
                provider_id = status.get("id")
                state = status.get("status")
                if not provider_id or not state:
                    continue
                statuses.append(
                    DeliveryUpdate(
                        provider_message_id=str(provider_id),
                        status=str(state),
                        occurred_at=_timestamp(status.get("timestamp")),
                        recipient_wa_id=status.get("recipient_id"),
                        phone_number_id=phone_number_id,
                        raw=status,
                    )
                )

    return ParsedWebhook(messages=messages, statuses=statuses)
