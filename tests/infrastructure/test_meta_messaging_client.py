"""Provider-shaped HTTP tests for Messenger and Instagram delivery."""

from __future__ import annotations

import json

import httpx

from realestate.channels.messaging import CustomerChannel
from realestate.channels.meta.client import MetaMessagingClient
from realestate.channels.whatsapp.client import SendOutcome


async def test_messenger_text_uses_the_bound_page_and_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"recipient_id": "psid-1", "message_id": "mid.sent.1"}
        )

    client = MetaMessagingClient(
        access_token="page-token",
        account_id="page-123",
        channel=CustomerChannel.FACEBOOK_MESSENGER,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.send_text("psid-1", "Hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.SENT
    assert result.provider_message_id == "mid.sent.1"
    assert seen[0].headers["Authorization"] == "Bearer page-token"
    assert seen[0].url.path.endswith("/page-123/messages")
    assert json.loads(seen[0].read()) == {
        "recipient": {"id": "psid-1"},
        "messaging_type": "RESPONSE",
        "message": {"text": "Hola"},
    }


async def test_instagram_text_uses_the_bound_account_without_messenger_type() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"recipient_id": "ig-user-1", "message_id": "mid.ig.sent"}
        )

    client = MetaMessagingClient(
        access_token="instagram-token",
        account_id="ig-account-123",
        channel=CustomerChannel.INSTAGRAM,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.send_text("ig-user-1", "Hola desde Instagram")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.SENT
    assert seen[0].url.host == "graph.instagram.com"
    assert seen[0].url.path.endswith("/ig-account-123/messages")
    assert json.loads(seen[0].read()) == {
        "recipient": {"id": "ig-user-1"},
        "message": {"text": "Hola desde Instagram"},
    }
