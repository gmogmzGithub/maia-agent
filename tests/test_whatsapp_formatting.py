"""WhatsApp's markup is not interchangeable with Markdown."""

from __future__ import annotations

import pytest

from realestate.channels.whatsapp.formatting import to_whatsapp_markup


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        ("**Casa Roble**", "*Casa Roble*"),
        ("__Casa Roble__", "*Casa Roble*"),
        ("**4 opciones** disponibles", "*4 opciones* disponibles"),
        ("**Casas:**\n\n* Casa Roble\n* Casa Encino", "*Casas:*\n\n* Casa Roble\n* Casa Encino"),
        ("**Precio:** $3,000,000\n_Consulta disponibilidad_", "*Precio:* $3,000,000\n_Consulta disponibilidad_"),
        ("~~No disponible~~", "~No disponible~"),
    ],
)
def test_common_model_markup_is_valid_whatsapp_markup(draft: str, expected: str) -> None:
    assert to_whatsapp_markup(draft) == expected


def test_existing_whatsapp_bold_is_not_changed_to_italics() -> None:
    assert to_whatsapp_markup("*Casa Roble*") == "*Casa Roble*"


def test_plain_text_and_empty_text_are_unchanged() -> None:
    assert to_whatsapp_markup("Casa Roble cuesta $3,000,000 MXN.") == (
        "Casa Roble cuesta $3,000,000 MXN."
    )
    assert to_whatsapp_markup("") == ""
