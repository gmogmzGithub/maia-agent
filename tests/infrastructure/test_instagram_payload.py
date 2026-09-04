"""Instagram webhook projection into Product messaging vocabulary."""

from __future__ import annotations

from realestate.channels.instagram.payload import parse_webhook
from realestate.channels.messaging import CustomerChannel
from tests.fixtures import instagram


def test_a_text_message_preserves_its_scoped_instagram_identity() -> None:
    parsed = parse_webhook(
        instagram.text_message(message_id="mid.instagram.1", body="Info, por favor")
    )

    assert len(parsed) == 1
    assert parsed[0].channel is CustomerChannel.INSTAGRAM
    assert parsed[0].provider_message_id == "mid.instagram.1"
    assert parsed[0].sender_id == instagram.SENDER_IGSID
    assert parsed[0].channel_account_id == instagram.ACCOUNT_ID
    assert parsed[0].text == "Info, por favor"
