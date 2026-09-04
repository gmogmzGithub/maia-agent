"""Channel-neutral values crossing from customer adapters into Product."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class CustomerChannel(str, enum.Enum):
    """An authorized customer-facing messaging channel."""

    WHATSAPP = "WhatsApp"
    FACEBOOK_MESSENGER = "FacebookMessenger"
    INSTAGRAM = "Instagram"


@dataclass(frozen=True)
class InboundMessage:
    """One provider-authenticated customer message in Product vocabulary."""

    channel: CustomerChannel
    provider_message_id: str
    sender_id: str
    channel_account_id: str
    message_type: str
    sent_at: datetime
    text: str | None
    profile_name: str | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def referral(self) -> dict[str, Any] | None:
        value = self.raw.get("referral")
        return value if isinstance(value, dict) else None


class InboundCustomerMessage(Protocol):
    """Structural input accepted by the durable Product Inbox."""

    @property
    def channel(self) -> CustomerChannel: ...

    @property
    def provider_message_id(self) -> str: ...

    @property
    def sender_id(self) -> str: ...

    @property
    def channel_account_id(self) -> str: ...

    @property
    def message_type(self) -> str: ...

    @property
    def sent_at(self) -> datetime: ...

    @property
    def text(self) -> str | None: ...

    @property
    def profile_name(self) -> str | None: ...

    @property
    def raw(self) -> dict[str, Any]: ...
