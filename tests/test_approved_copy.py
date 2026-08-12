"""Canonicalisation of approved Lead-facing copy (P-049, P-063, ADR-0013).

Keeps what the Lead receives consistent when the Model drifts on accents,
punctuation, or casing. The byte-exact wording of the clarification is *not* a
requirement — Cliente Demo relaxed that, since the discovery documents' capital
"NO" was his typing habit rather than intended copy. What the suite still pins
is that an approved message, once emitted, is released in one consistent form.
"""

from __future__ import annotations

import pytest

from realestate.domain.copy import (
    PROPERTY_CLARIFICATION,
    PROPERTY_UNAVAILABLE,
    canonicalize,
)


def test_the_canonical_clarification_uses_ordinary_capitalisation() -> None:
    # Natural phrasing, not the shouted form. Behaviour is enforced by the
    # guide and asserted in the conversation suite, not by these bytes.
    assert PROPERTY_CLARIFICATION.startswith("No estoy seguro")


def test_the_exact_copy_is_left_untouched() -> None:
    result = canonicalize(PROPERTY_CLARIFICATION)

    assert result.text == PROPERTY_CLARIFICATION
    assert not result.changed


@pytest.mark.parametrize(
    "draft",
    [
        "no estoy seguro de cuál propiedad estás buscando, me puedes decir más detalles?",
        "No estoy seguro de cual propiedad estas buscando, me puedes decir mas detalles?",
        "¿No estoy seguro de cuál propiedad estás buscando, me puedes decir más detalles?",
        "No estoy seguro de cuál propiedad estás buscando, me puedes decir más detalles.",
    ],
)
def test_a_reworded_clarification_is_restored(draft: str) -> None:
    result = canonicalize(draft)

    assert PROPERTY_CLARIFICATION in result.text, result.text
    assert result.changed


def test_the_unavailable_message_is_restored_too() -> None:
    draft = (
        "Lo siento, esta propiedad ya no esta disponible para agendar una visita. "
        "Si quieres, puedo pedirle al concierge que te contacte."
    )

    result = canonicalize(draft)

    assert PROPERTY_UNAVAILABLE in result.text
    assert result.changed


def test_an_unrelated_reply_is_never_rewritten() -> None:
    draft = "Casa Roble cuesta $3,000,000 MXN. ¿Quieres agendar una visita?"

    result = canonicalize(draft)

    assert result.text == draft
    assert not result.changed


def test_a_genuine_paraphrase_is_not_invented_into_the_approved_copy() -> None:
    # Canonicalisation restores wording; it does not decide that a reply
    # *should* have been an approved message. That would be intent inference,
    # which ADR-0013 forbids.
    draft = "¿Cuál propiedad te interesa?"

    result = canonicalize(draft)

    assert result.text == draft
    assert not result.changed


def test_surrounding_text_is_preserved() -> None:
    draft = (
        "¡Hola!\n"
        "No estoy seguro de cuál propiedad estás buscando, me puedes decir más detalles?\n"
        "Con gusto te ayudo."
    )

    result = canonicalize(draft)

    assert PROPERTY_CLARIFICATION in result.text
    assert "¡Hola!" in result.text
    assert "Con gusto te ayudo." in result.text


def test_an_empty_draft_is_safe() -> None:
    assert canonicalize("").text == ""


# --- The sentence embedded in a longer paragraph ------------------------------


def test_a_reworded_sentence_inside_a_paragraph_is_restored() -> None:
    """The line-by-line pass misses this shape; the approximate pattern catches
    it. Models routinely run the sentence together with a greeting."""
    draft = (
        "¡Hola! no estoy seguro de cual propiedad estas buscando "
        "me puedes decir mas detalles? Con gusto te ayudo."
    )

    result = canonicalize(draft)

    assert PROPERTY_CLARIFICATION in result.text
    assert result.replaced == (PROPERTY_CLARIFICATION,)
    assert result.text.startswith("¡Hola! ")
    assert result.text.endswith(" Con gusto te ayudo.")


def test_an_inverted_opening_mark_is_absorbed_rather_than_left_behind() -> None:
    draft = "Antes de seguir: ¿no estoy seguro de cual propiedad estas buscando, me puedes decir mas detalles? Gracias."

    result = canonicalize(draft)

    assert PROPERTY_CLARIFICATION in result.text
    assert "¿No estoy" not in result.text


def test_accented_and_unaccented_letters_both_match_inside_a_paragraph() -> None:
    draft = (
        "Mira, ño estoy segúro de cuál propiedad estás buscando, "
        "me puedes decir más detalles? — dime cuál."
    )

    result = canonicalize(draft)

    assert PROPERTY_CLARIFICATION in result.text


def test_the_unavailable_message_is_restored_when_it_is_its_own_line() -> None:
    draft = (
        "Un momento.\n"
        "lo siento, esta propiedad ya no esta disponible para agendar una visita. "
        "si quieres, puedo pedirle al concierge que te contacte.\n"
        "Un saludo."
    )

    result = canonicalize(draft)

    assert PROPERTY_UNAVAILABLE in result.text
    assert result.replaced == (PROPERTY_UNAVAILABLE,)


def test_a_two_sentence_message_run_into_a_paragraph_is_left_alone() -> None:
    r"""A known limitation, pinned rather than papered over.

    ``_approximate_pattern`` separates words with ``[\s,;:]*``, which does not
    span the full stop inside PROPERTY_UNAVAILABLE. So when the Model runs that
    two-sentence message together with other prose on one line, the wording is
    released as the Model wrote it. The single-sentence clarification — the
    common case — is unaffected, and leaving the draft intact is the safe
    failure: canonicalisation never mangles text it cannot place.
    """
    draft = (
        "Lo siento esta propiedad ya no esta disponible para agendar una visita. "
        "Si quieres puedo pedirle al concierge que te contacte. Un saludo."
    )

    result = canonicalize(draft)

    assert result.text == draft
    assert not result.changed


def test_both_approved_messages_in_one_draft_are_each_restored() -> None:
    draft = (
        "no estoy seguro de cual propiedad estas buscando, me puedes decir mas detalles?\n"
        "lo siento, esta propiedad ya no esta disponible para agendar una visita. "
        "si quieres, puedo pedirle al concierge que te contacte."
    )

    result = canonicalize(draft)

    assert set(result.replaced) == {PROPERTY_CLARIFICATION, PROPERTY_UNAVAILABLE}


def test_a_sentence_already_exact_inside_a_paragraph_is_not_rewritten() -> None:
    draft = f"¡Hola! {PROPERTY_CLARIFICATION} Con gusto te ayudo."

    result = canonicalize(draft)

    assert result.text == draft
    assert not result.changed


def test_a_near_miss_the_pattern_cannot_place_leaves_the_draft_alone() -> None:
    """The fold matches but the words are reordered, so no substitution is made
    — better an unchanged draft than a mangled one."""
    draft = "detalles decir puedes me buscando estas propiedad cual de seguro estoy no"

    result = canonicalize(draft)

    assert result.text == draft
    assert not result.changed


def test_an_approved_message_that_folds_to_nothing_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A punctuation-only entry would otherwise match every line in the draft."""
    import realestate.domain.copy as copy_module

    monkeypatch.setattr(copy_module, "APPROVED_MESSAGES", ("¿?", PROPERTY_CLARIFICATION))

    result = copy_module.canonicalize("Hola, ¿en qué te ayudo?")

    assert result.text == "Hola, ¿en qué te ayudo?"
    assert not result.changed


def test_a_reply_of_only_whitespace_is_left_exactly_as_it_is() -> None:
    assert canonicalize("   ").text == "   "


def test_the_replaced_list_is_empty_when_nothing_changed() -> None:
    result = canonicalize("Casa Roble tiene 4 recámaras.")

    assert result.replaced == ()
    assert not result.changed
