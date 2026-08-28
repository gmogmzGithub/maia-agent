"""Text folding shared by the domain.

Spanish copy is compared in several unrelated places — Property name uniqueness
(P-048), approved-message canonicalisation (ADR-0013), and opt-out recognition
(ADR-0045) — and all of them must agree on what counts as the same letter. The
folds live here so teaching them about a character teaches every caller.

One fold here is not about letters at all: Mexico's optional mobile ``1``. It
lives beside the others for the same reason — the send path and the duplicate
detector must agree about it, and if they ever disagree Product will show two
Contacts as unrelated while delivering both messages to one phone.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_NON_DIGITS = re.compile(r"\D")


def strip_diacritics(value: str) -> str:
    """Drop combining marks, so ``cása`` and ``casa`` compare equal."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold_phrase(value: str) -> str:
    """Reduce a message to comparable words: case, accents, punctuation, spacing.

    Stronger than :func:`strip_diacritics` alone, because the things compared
    against it are whole phrases a person typed rather than a single stored
    name. ``"¡NO ME CONTÁCTES!"`` and ``"no me contactes"`` fold together.
    """
    folded = strip_diacritics(value).casefold()
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", folded)).strip()


def fold_mexican_mobile(value: str) -> str:
    """The digits of a phone identifier with Mexico's optional ``1`` removed.

    Mexican mobile numbers carry a legacy ``1`` after the country code. Meta
    reports inbound senders as ``521XXXXXXXXXX`` but rejects that same string as
    a send target on the test number's allowlist, which stores
    ``52XXXXXXXXXX``. Observed directly: replying to the exact ``wa_id`` Meta
    gave us failed with ``131030 Recipient phone number not in allowed list``,
    while the un-prefixed form delivered.

    Only ``521`` + 10 digits is touched. Everything else keeps its digits, so
    this cannot silently mangle another country's numbering. It returns digits
    only — callers that need a fallback for a non-numeric input supply their own.
    """
    digits = _NON_DIGITS.sub("", value)
    if len(digits) == 13 and digits.startswith("521"):
        return "52" + digits[3:]
    return digits
