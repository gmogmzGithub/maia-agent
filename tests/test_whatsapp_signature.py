"""Meta webhook authentication (TC-006, ADR-0005).

Exercised against the project's real configured App Secret, so these assert the
behaviour Meta will actually produce rather than a stand-in.
"""

from __future__ import annotations

import pytest

from realestate.channels.whatsapp.signature import (
    compute_signature,
    is_valid_signature,
)
from tests.conftest import env

SECRET = env("META_APP_SECRET") or "test-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def test_a_correct_signature_is_accepted() -> None:
    assert is_valid_signature(SECRET, BODY, compute_signature(SECRET, BODY))


def test_the_digest_matches_metas_documented_algorithm() -> None:
    # sha256= + HMAC-SHA256(app secret, raw body), hex.
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(
        SECRET.encode(), BODY, hashlib.sha256
    ).hexdigest()

    assert compute_signature(SECRET, BODY) == expected


def test_a_tampered_body_is_rejected() -> None:
    signature = compute_signature(SECRET, BODY)

    assert not is_valid_signature(SECRET, BODY + b" ", signature)


def test_a_signature_from_a_different_secret_is_rejected() -> None:
    forged = compute_signature("not-the-app-secret", BODY)

    assert not is_valid_signature(SECRET, BODY, forged)


@pytest.mark.parametrize(
    "header",
    [None, "", "sha256=", "deadbeef", "sha1=deadbeef", "sha256=nothexatall"],
)
def test_malformed_headers_are_rejected_without_raising(header: str | None) -> None:
    assert not is_valid_signature(SECRET, BODY, header)


def test_an_unconfigured_secret_never_authenticates() -> None:
    # A blank secret must fail closed, not accept everything.
    assert not is_valid_signature("", BODY, compute_signature("", BODY))


def test_the_signature_covers_the_exact_bytes() -> None:
    """Re-serialising the JSON would change the digest, so raw bytes are used."""
    reserialised = b'{"object": "whatsapp_business_account", "entry": []}'

    assert not is_valid_signature(SECRET, reserialised, compute_signature(SECRET, BODY))
