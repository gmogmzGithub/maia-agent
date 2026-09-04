"""Outbound Facebook Messenger and Instagram Messaging delivery."""

from __future__ import annotations

from typing import Any

import httpx

from realestate.channels.messaging import CustomerChannel
from realestate.channels.whatsapp.client import SendOutcome, SendResult, WhatsAppClient


class MetaMessagingClient(WhatsAppClient):
    """Send free-form replies through one Page or Instagram account.

    The transport and outcome policy are identical to WhatsApp's: retry only a
    request known not to have succeeded, and quarantine an ambiguous result.
    """

    def __init__(
        self,
        access_token: str,
        account_id: str,
        channel: CustomerChannel,
        graph_version: str = "v25.0",
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if channel not in {
            CustomerChannel.FACEBOOK_MESSENGER,
            CustomerChannel.INSTAGRAM,
        }:
            raise ValueError(f"Unsupported Meta messaging channel: {channel.value}")
        resolved_base_url = base_url or (
            "https://graph.instagram.com"
            if channel is CustomerChannel.INSTAGRAM
            else "https://graph.facebook.com"
        )
        super().__init__(
            access_token=access_token,
            phone_number_id=account_id,
            graph_version=graph_version,
            base_url=resolved_base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self.channel = channel

    async def send_text(self, recipient_id: str, body: str) -> SendResult:
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "message": {"text": body},
        }
        if self.channel is CustomerChannel.FACEBOOK_MESSENGER:
            payload["messaging_type"] = "RESPONSE"
        return await self._post("/messages", payload)

    async def send_template(
        self, recipient_id: str, template_id: str, language_code: str
    ) -> SendResult:
        del recipient_id, template_id, language_code
        return SendResult(
            SendOutcome.FAILED_PERMANENT,
            detail=f"{self.channel.value} templates are not configured.",
        )

    def _classify(self, response: httpx.Response) -> SendResult:
        if response.status_code != 200:
            return super()._classify(response)
        try:
            body = response.json()
        except ValueError:
            return SendResult(
                SendOutcome.UNKNOWN,
                detail="Meta returned 200 with an unreadable body.",
            )
        provider_id = body.get("message_id") if isinstance(body, dict) else None
        if not provider_id:
            return SendResult(
                SendOutcome.UNKNOWN,
                detail="Meta returned 200 without a message id.",
            )
        return SendResult(SendOutcome.SENT, provider_message_id=str(provider_id))
