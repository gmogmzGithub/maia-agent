"""Mexican mobile numbers need the legacy `1` stripped before sending.

Found on the first live WhatsApp round trip: Meta reported the Lead's `wa_id`
as `5213318923936`, we replied to exactly that, and Meta answered
`131030 Recipient phone number not in allowed list` — while the same phone as
`523318923936` delivered fine.
"""

from __future__ import annotations

import pytest

from realestate.channels.whatsapp.client import normalize_recipient


def test_a_mexican_mobile_loses_the_legacy_one() -> None:
    assert normalize_recipient("5213318923936") == "523318923936"


def test_an_already_normalised_mexican_number_is_unchanged() -> None:
    assert normalize_recipient("523318923936") == "523318923936"


@pytest.mark.parametrize(
    "wa_id",
    [
        "5215512345678",  # Mexico City mobile
        "5213312345678",  # Guadalajara mobile
    ],
)
def test_every_mexican_mobile_shape_normalises(wa_id: str) -> None:
    result = normalize_recipient(wa_id)

    assert result.startswith("52")
    assert len(result) == 12


@pytest.mark.parametrize(
    "wa_id",
    [
        "12125551234",       # US
        "5491112345678",     # Argentina, also 13 digits but starts 549
        "521",               # too short to be a number
        "34612345678",       # Spain
        "5213318923936000",  # too long
    ],
)
def test_other_numbering_plans_are_left_alone(wa_id: str) -> None:
    assert normalize_recipient(wa_id) == wa_id


def test_formatting_characters_are_stripped() -> None:
    assert normalize_recipient("+52 1 33 1892-3936") == "523318923936"


def test_a_non_numeric_value_is_returned_unchanged() -> None:
    # Defensive: never turn a bad input into an empty recipient.
    assert normalize_recipient("not-a-number") == "not-a-number"
