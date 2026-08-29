"""Parsing the Meta webhook body: tolerant on purpose.

Meta adds fields, sends types Stage 0 does not handle, and batches several
entries into one request. Rejecting a body would make Meta retry something that
will never parse, so anything unrecognised is skipped instead — but "skipped"
must mean *that item*, never the valid siblings beside it.

The other invariant is retention: the complete authenticated message object is
carried through untouched, because the Inbox stores it and V-001 has yet to
confirm what a real Click-to-WhatsApp referral looks like (P-049, TC-009).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from realestate.channels.whatsapp.payload import parse_webhook
from tests.fixtures import webhooks

PHONE_ID = webhooks.PHONE_NUMBER_ID
LEAD = webhooks.LEAD_WA_ID


def envelope(value: Any) -> dict:
    return {"entry": [{"changes": [{"field": "messages", "value": value}]}]}


def with_messages(*messages: Any, contacts: list | None = None) -> dict:
    return envelope(
        {
            "metadata": {"phone_number_id": PHONE_ID},
            "contacts": contacts if contacts is not None else [],
            "messages": list(messages),
        }
    )


def a_message(**overrides: Any) -> dict:
    base = {
        "from": LEAD,
        "id": "wamid.1",
        "timestamp": "1770000000",
        "type": "text",
        "text": {"body": "hola"},
    }
    base.update(overrides)
    return base


# -- Nothing to parse -----------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"entry": []},
        {"entry": None},
        {"entry": ["not-a-dict"]},
        {"entry": [{}]},
        {"entry": [{"changes": None}]},
        {"entry": [{"changes": ["not-a-dict"]}]},
        {"entry": [{"changes": [{}]}]},
        {"entry": [{"changes": [{"value": None}]}]},
        {"entry": [{"changes": [{"value": "not-a-dict"}]}]},
    ],
)
def test_a_body_with_nothing_usable_parses_to_nothing(body: dict) -> None:
    """Never an exception: a 500 here would make Meta retry the same body."""
    parsed = parse_webhook(body)

    assert parsed.messages == [] and parsed.statuses == []


def test_a_change_with_neither_messages_nor_statuses_is_empty() -> None:
    parsed = parse_webhook(envelope({"metadata": {"phone_number_id": PHONE_ID}}))

    assert parsed.messages == [] and parsed.statuses == []


# -- Messages -------------------------------------------------------------------


def test_a_text_message_carries_its_identity_and_words() -> None:
    parsed = parse_webhook(
        with_messages(
            a_message(),
            contacts=[{"wa_id": LEAD, "profile": {"name": "Cliente Demo"}}],
        )
    )

    message = parsed.messages[0]
    assert message.wamid == "wamid.1"
    assert message.from_wa_id == LEAD
    assert message.phone_number_id == PHONE_ID
    assert message.message_type == "text"
    assert message.text == "hola"
    assert message.profile_name == "Cliente Demo"
    assert message.sent_at == datetime.fromtimestamp(1770000000, tz=UTC)


@pytest.mark.parametrize(
    "message",
    ["not-a-dict", {"id": "wamid.1"}, {"from": LEAD}, {"id": "", "from": LEAD}],
)
def test_a_message_that_cannot_be_identified_is_skipped(message: Any) -> None:
    assert parse_webhook(with_messages(message)).messages == []


def test_one_unusable_message_does_not_hide_a_valid_sibling() -> None:
    parsed = parse_webhook(with_messages({"id": "no-sender"}, a_message(id="wamid.2")))

    assert [m.wamid for m in parsed.messages] == ["wamid.2"]


def test_several_entries_in_one_request_are_all_parsed() -> None:
    """Meta batches; a request is not one message."""
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_ID},
                            "messages": [a_message(id="wamid.1")],
                        }
                    }
                ]
            },
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_ID},
                            "messages": [a_message(id="wamid.2")],
                        }
                    }
                ]
            },
        ]
    }

    assert [m.wamid for m in parse_webhook(body).messages] == ["wamid.1", "wamid.2"]


def test_a_message_with_no_metadata_still_parses() -> None:
    parsed = parse_webhook(envelope({"messages": [a_message()]}))

    assert parsed.messages[0].phone_number_id == ""


def test_an_unknown_message_type_is_retained_without_text() -> None:
    """Stage 0 cannot act on it, but the Inbox still records it arrived."""
    parsed = parse_webhook(with_messages(a_message(type="location", location={})))

    assert parsed.messages[0].message_type == "location"
    assert parsed.messages[0].text is None


def test_a_message_with_no_type_at_all_is_recorded_as_unknown() -> None:
    parsed = parse_webhook(with_messages({"id": "wamid.1", "from": LEAD}))

    assert parsed.messages[0].message_type == "unknown"


# -- The text of the shapes Stage 0 can act on ----------------------------------


def test_a_button_reply_reads_as_its_label() -> None:
    parsed = parse_webhook(
        with_messages(a_message(type="button", button={"text": "Sí, me interesa"}))
    )

    assert parsed.messages[0].text == "Sí, me interesa"


@pytest.mark.parametrize("key", ["button_reply", "list_reply"])
def test_an_interactive_reply_reads_as_its_title(key: str) -> None:
    parsed = parse_webhook(
        with_messages(
            a_message(type="interactive", interactive={key: {"title": "Casa Roble"}})
        )
    )

    assert parsed.messages[0].text == "Casa Roble"


@pytest.mark.parametrize(
    "message",
    [
        {"type": "text", "text": None},
        {"type": "text", "text": {"body": None}},
        {"type": "text", "text": {"body": ["hola"]}},
        {"type": "button", "button": None},
        {"type": "button", "button": {}},
        {"type": "interactive", "interactive": None},
        {"type": "interactive", "interactive": {}},
        {"type": "interactive", "interactive": {"button_reply": "not-a-dict"}},
    ],
)
def test_a_malformed_body_reads_as_no_text_rather_than_raising(message: dict) -> None:
    parsed = parse_webhook(with_messages(a_message(**message)))

    assert parsed.messages[0].text is None


# -- Timestamps -------------------------------------------------------------------


@pytest.mark.parametrize("timestamp", [None, "", "not-a-number", {"seconds": 1}, []])
def test_an_unreadable_timestamp_falls_back_to_now(timestamp: Any) -> None:
    before = datetime.now(tz=UTC)

    parsed = parse_webhook(with_messages(a_message(timestamp=timestamp)))

    assert before <= parsed.messages[0].sent_at <= datetime.now(tz=UTC)


def test_a_numeric_timestamp_is_accepted_as_well_as_a_string() -> None:
    parsed = parse_webhook(with_messages(a_message(timestamp=1770000000)))

    assert parsed.messages[0].sent_at == datetime.fromtimestamp(1770000000, tz=UTC)


# -- Profile names ----------------------------------------------------------------


def test_a_contact_without_a_profile_yields_no_name() -> None:
    parsed = parse_webhook(
        with_messages(a_message(), contacts=[{"wa_id": LEAD}])
    )

    assert parsed.messages[0].profile_name is None


def test_a_non_dict_contact_is_skipped_without_losing_the_message() -> None:
    parsed = parse_webhook(with_messages(a_message(), contacts=["not-a-dict"]))

    assert parsed.messages[0].profile_name is None


def test_a_name_is_matched_to_its_own_sender() -> None:
    parsed = parse_webhook(
        with_messages(
            a_message(id="wamid.1", **{"from": "521111"}),
            a_message(id="wamid.2", **{"from": "521222"}),
            contacts=[
                {"wa_id": "521111", "profile": {"name": "Ana"}},
                {"wa_id": "521222", "profile": {"name": "Beto"}},
            ],
        )
    )

    assert [m.profile_name for m in parsed.messages] == ["Ana", "Beto"]


# -- Referral (unproven until V-001) ----------------------------------------------


def test_a_referral_block_is_surfaced_untouched() -> None:
    parsed = parse_webhook(
        with_messages(a_message(referral=dict(webhooks.SAMPLE_REFERRAL)))
    )

    assert parsed.messages[0].referral == webhooks.SAMPLE_REFERRAL
    # And retained whole on the raw object the Inbox stores.
    assert parsed.messages[0].raw["referral"] == webhooks.SAMPLE_REFERRAL


@pytest.mark.parametrize("referral", [None, "not-a-dict", 42, []])
def test_anything_that_is_not_a_referral_object_reads_as_absent(referral: Any) -> None:
    """No Property mapping is derived from this field until V-001 proves it."""
    parsed = parse_webhook(with_messages(a_message(referral=referral)))

    assert parsed.messages[0].referral is None


def test_a_message_with_no_referral_reads_as_absent() -> None:
    assert parse_webhook(with_messages(a_message())).messages[0].referral is None


# -- Delivery statuses ---------------------------------------------------------------


def test_a_delivery_status_carries_its_provider_id_and_state() -> None:
    parsed = parse_webhook(
        webhooks.status_update(provider_message_id="wamid.OUT", status="delivered")
    )

    update = parsed.statuses[0]
    assert update.provider_message_id == "wamid.OUT"
    assert update.status == "delivered"
    assert update.recipient_wa_id == LEAD


@pytest.mark.parametrize(
    "status",
    [
        "not-a-dict",
        {"status": "delivered"},
        {"id": "wamid.OUT"},
        {"id": "", "status": "delivered"},
        {"id": "wamid.OUT", "status": ""},
    ],
)
def test_an_incomplete_status_is_skipped(status: Any) -> None:
    parsed = parse_webhook(
        envelope({"metadata": {"phone_number_id": PHONE_ID}, "statuses": [status]})
    )

    assert parsed.statuses == []


def test_one_incomplete_status_does_not_hide_a_valid_sibling() -> None:
    parsed = parse_webhook(
        envelope(
            {
                "metadata": {"phone_number_id": PHONE_ID},
                "statuses": [
                    {"status": "read"},
                    {"id": "wamid.OUT", "status": "read", "timestamp": "1770000000"},
                ],
            }
        )
    )

    assert [s.provider_message_id for s in parsed.statuses] == ["wamid.OUT"]


def test_a_status_without_a_recipient_still_parses() -> None:
    parsed = parse_webhook(
        envelope(
            {
                "metadata": {"phone_number_id": PHONE_ID},
                "statuses": [{"id": "wamid.OUT", "status": "failed"}],
            }
        )
    )

    assert parsed.statuses[0].recipient_wa_id is None


def test_messages_and_statuses_in_one_change_are_both_parsed() -> None:
    parsed = parse_webhook(
        envelope(
            {
                "metadata": {"phone_number_id": PHONE_ID},
                "messages": [a_message()],
                "statuses": [
                    {"id": "wamid.OUT", "status": "sent", "timestamp": "1770000000"}
                ],
            }
        )
    )

    assert len(parsed.messages) == 1 and len(parsed.statuses) == 1
