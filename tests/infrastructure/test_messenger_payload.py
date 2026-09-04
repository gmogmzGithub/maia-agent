"""Facebook Page Messenger payloads become channel-neutral customer messages."""

from __future__ import annotations

from datetime import UTC, datetime

from realestate.channels.messaging import CustomerChannel
from realestate.channels.messenger.payload import parse_webhook


def test_a_page_message_carries_the_provider_identity_and_words() -> None:
    body = {
        "object": "page",
        "entry": [
            {
                "id": "page-123",
                "time": 1770000000000,
                "messaging": [
                    {
                        "sender": {"id": "psid-456"},
                        "recipient": {"id": "page-123"},
                        "timestamp": 1770000000000,
                        "message": {"mid": "mid.facebook.1", "text": "Hola"},
                    }
                ],
            }
        ],
    }

    messages = parse_webhook(body)

    assert len(messages) == 1
    message = messages[0]
    assert message.channel is CustomerChannel.FACEBOOK_MESSENGER
    assert message.provider_message_id == "mid.facebook.1"
    assert message.sender_id == "psid-456"
    assert message.channel_account_id == "page-123"
    assert message.message_type == "text"
    assert message.text == "Hola"
    assert message.sent_at == datetime.fromtimestamp(1770000000, tz=UTC)
    assert message.raw == body["entry"][0]["messaging"][0]
