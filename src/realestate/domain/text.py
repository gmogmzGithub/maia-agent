"""Text folding shared by the domain.

Spanish copy is compared in two unrelated places — Property name uniqueness
(P-048) and approved-message canonicalisation (ADR-0013) — and both must agree
on what counts as the same letter. The fold lives here so teaching it about a
character teaches both.
"""

from __future__ import annotations

import unicodedata


def strip_diacritics(value: str) -> str:
    """Drop combining marks, so ``cása`` and ``casa`` compare equal."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
