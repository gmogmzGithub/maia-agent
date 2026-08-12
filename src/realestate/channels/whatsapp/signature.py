"""Meta webhook payload authentication (TC-006, ADR-0005).

Meta signs the raw request body with the app secret. The Inbox authenticates
every payload *before* persisting or acknowledging it, so an unsigned or
tampered body never becomes product state.

The comparison is constant-time and operates on the exact bytes received: any
re-serialisation of the JSON would change the digest.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def compute_signature(app_secret: str, body: bytes) -> str:
    """Return the header value Meta would send for *body*."""
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def is_valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """True when *header* is Meta's signature for *body*.

    Returns False rather than raising for every malformed input: a missing
    secret, a missing header, or the wrong prefix are all simply "not
    authenticated".
    """
    if not app_secret or not header or not header.startswith(_PREFIX):
        return False
    # Compared as bytes: hmac.compare_digest raises TypeError on str inputs that
    # are not pure ASCII, and a header is attacker-supplied, so comparing as str
    # would raise instead of honouring this function's "never raises" contract.
    return hmac.compare_digest(
        compute_signature(app_secret, body).encode("utf-8"), header.encode("utf-8")
    )
