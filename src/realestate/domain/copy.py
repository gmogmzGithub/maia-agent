"""Approved Lead-facing copy, and canonicalisation of it (ADR-0013).

The Product Harness owns "the small set of accepted deterministic messages".
Some of those the Harness *originates* — the booking confirmation, the
processing-failure notice. This module handles the other kind: copy the Model is
expected to produce verbatim, which it reliably rewords.

Its job is narrow: when the Model emits an accepted message but drifts on
accents, punctuation, or casing, the released text is restored to one approved
form. That keeps what the Lead receives consistent across models and runs.

This is canonicalisation, not intent inference. It never *decides* that a reply
should have been an approved message — it only rewrites text the Model already
chose to emit. A reply that does not contain the sentence is left alone, which
is why the guide still has to do its job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, tzinfo

from realestate.domain.text import strip_diacritics

# P-049: the Agent's reply when neither inbound evidence nor the Lead's text
# identifies one Property.
#
# The discovery documents write this with a capital "NO". Cliente Demo has since
# clarified that this was his own typing habit rather than intended copy, and
# that the model's natural phrasing is preferred — so the canonical form uses
# ordinary capitalisation. Shouting at a Lead was never the goal.
#
# What is NOT relaxed is the behaviour underneath: the Agent must ask which
# Property and must never guess one. That is asserted separately and did not
# vary on any model.
PROPERTY_CLARIFICATION = (
    "No estoy seguro de cuál propiedad estás buscando, me puedes decir más detalles?"
)

# P-063: the reply when a Property is no longer available for a visit.
PROPERTY_UNAVAILABLE = (
    "Lo siento, esta propiedad ya no está disponible para agendar una visita. "
    "Si quieres, puedo pedirle al concierge que te contacte."
)

APPROVED_MESSAGES: tuple[str, ...] = (
    PROPERTY_CLARIFICATION,
    PROPERTY_UNAVAILABLE,
)

# Spelled out rather than taken from the C locale, which is not guaranteed to be
# installed and would silently produce English.
SPANISH_DAYS = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)


def visit_stamp(moment: datetime, zone: tzinfo) -> str:
    """When a visit happens, as Product writes it to a person.

    One spelling, because the Contact's reminder and the Advisor's notice are
    about the same appointment and two renderings of it read as two visits.
    """
    local = moment.astimezone(zone)
    return (
        f"{SPANISH_DAYS[local.weekday()]} {local.strftime('%d/%m')} a las "
        f"{local.strftime('%H:%M')}"
    )


def _loose(text: str) -> str:
    """Fold text for matching: case, accents, punctuation, and whitespace.

    Deliberately generous. A near-miss on an approved message is exactly the
    case worth catching; the risk of a false positive is low because these
    sentences are long and specific.
    """
    return re.sub(r"[^a-z0-9 ]+", "", strip_diacritics(text).lower())


@dataclass(frozen=True)
class Canonicalisation:
    text: str
    replaced: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.replaced)


def canonicalize(draft: str) -> Canonicalisation:
    """Restore the approved wording of any accepted message inside *draft*.

    Matching ignores case, accents, and punctuation, so ``No estoy seguro de
    cual propiedad estas buscando, me puedes decir mas detalles?`` is recognised
    and replaced with the approved form. Everything around it is preserved.
    """
    if not draft:
        return Canonicalisation(text=draft)

    text = draft
    replaced: list[str] = []

    for approved in APPROVED_MESSAGES:
        target = _loose(approved)
        if not target:
            continue

        # Walk the draft's sentences and swap any that fold to the approved one.
        pieces = re.split(r"(\n+)", text)
        rebuilt: list[str] = []
        hit = False
        for piece in pieces:
            if _loose(piece) == target and piece.strip() != approved:
                rebuilt.append(approved)
                hit = True
            else:
                rebuilt.append(piece)
        if hit:
            text = "".join(rebuilt)
            replaced.append(approved)
            continue

        # Also handle the sentence embedded in a longer paragraph.
        if target in _loose(text) and approved not in text:
            pattern = _approximate_pattern(approved)
            new_text, count = pattern.subn(approved, text, count=1)
            if count:
                text = new_text
                replaced.append(approved)

    return Canonicalisation(text=text, replaced=tuple(replaced))


def _approximate_pattern(approved: str) -> re.Pattern[str]:
    """A regex matching *approved* ignoring case, accents, and punctuation."""
    parts = []
    for word in _loose(approved).split():
        # Each ASCII letter also matches its accented forms.
        chars = "".join(
            f"[{c}{c.upper()}{_accents(c)}]" if c.isalpha() else re.escape(c)
            for c in word
        )
        parts.append(chars)
    # Words separated by whitespace, with optional punctuation between them.
    return re.compile(r"[¿¡]?" + r"[\s,;:]*".join(parts) + r"[.?!]?", re.UNICODE)


_ACCENTS = {
    "a": "áàäâ", "e": "éèëê", "i": "íìïî", "o": "óòöô", "u": "úùüû", "n": "ñ",
    "c": "ç",
}


def _accents(letter: str) -> str:
    lower = _ACCENTS.get(letter, "")
    return lower + lower.upper()
