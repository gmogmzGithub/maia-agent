"""Text folding shared by the domain.

Spanish copy is compared in several unrelated places — Property name uniqueness
(P-048), approved-message canonicalisation (ADR-0013), and opt-out recognition
(ADR-0045) — and all of them must agree on what counts as the same letter. The
folds live here so teaching them about a character teaches every caller.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


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
