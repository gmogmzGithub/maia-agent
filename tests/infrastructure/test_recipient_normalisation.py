"""Mexican mobile numbers need the legacy `1` stripped before sending.

The provider behavior was established in a live WhatsApp round trip. Concrete
recipient digits below are synthetic so this public test records the numbering
contract without publishing an allowlisted person's phone number.
"""

from __future__ import annotations

import pytest

from realestate.channels.whatsapp.client import normalize_recipient


def test_a_mexican_mobile_loses_the_legacy_one() -> None:
    assert normalize_recipient("5210000000000") == "520000000000"


def test_an_already_normalised_mexican_number_is_unchanged() -> None:
    assert normalize_recipient("520000000000") == "520000000000"


@pytest.mark.parametrize(
    "wa_id",
    [
        "5215500000000",  # synthetic Mexico City-shaped mobile
        "5213300000000",  # synthetic Guadalajara-shaped mobile
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
        "5210000000000000",  # too long
    ],
)
def test_other_numbering_plans_are_left_alone(wa_id: str) -> None:
    assert normalize_recipient(wa_id) == wa_id


def test_formatting_characters_are_stripped() -> None:
    assert normalize_recipient("+52 1 00 0000-0000") == "520000000000"


def test_a_non_numeric_value_is_returned_unchanged() -> None:
    # Defensive: never turn a bad input into an empty recipient.
    assert normalize_recipient("not-a-number") == "not-a-number"
