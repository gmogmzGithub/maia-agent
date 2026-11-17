import uuid

import pytest

from datalayer.models import Conversation, Message
from datalayer.whatsapp import queue_reply
from harness.presentation.properties import (
    property_highlights,
    property_text,
    repeats_card_details,
    split_closing_question,
)


def card(**changes):
    return {
        "id": 3,
        "reference": "PRUEBA-003",
        "title": "Departamento en Jardines",
        "price": "24000.00",
        "operation": "rent",
        "neighborhood": "Jardines Universidad",
        "municipality": "Zapopan",
        "bedrooms": 2,
        "bathrooms": "2.00",
        "parking": 1,
        "furnished": True,
        "accepts_pets": True,
        "near_schools": None,
        "unconfirmed": ["near_schools"],
        **changes,
    }


def test_public_card_formats_monthly_price_and_preserves_disclosures():
    text = property_text(card(), {"accepts_pets": True}, "https://sandbox.elmenlabs.com")
    assert "$24,000 MXN al mes" in text
    assert "Acepta mascotas" in text
    assert "Por confirmar: Escuelas cercanas" in text
    assert "no es una oferta comercial" in text
    assert text.count("/propiedades/3") == 1
    assert "24000.00" not in text and "ID 3" not in text
    assert "al mes" not in property_text(card(operation="sale"), {}, "https://example.test")


def test_highlights_prioritize_requested_known_facts_and_cap_at_three():
    assert property_highlights(card(), {"accepts_pets": True, "furnished": True}) == [
        "Amueblado",
        "Acepta mascotas",
        "2 recámaras",
    ]
    assert "Escuelas cercanas" not in property_highlights(card(), {"near_schools": True})


def test_duplicate_trial_disclosure_is_part_of_card_copy_repair():
    assert repeats_card_details("Es una propiedad de prueba, no una oferta comercial real.", [card()])
    assert not repeats_card_details("Te comparto esta opción. ¿Quieres conocer más detalles?", [card()])


def test_name_question_keeps_its_intro_after_cards():
    assert split_closing_question("Estas son las opciones. Por cierto, ¿cómo te llamas?") == (
        "Estas son las opciones.", "Por cierto, ¿cómo te llamas?",
    )


@pytest.mark.django_db(transaction=True)
def test_whatsapp_cards_have_one_public_link_each_and_keep_limit(settings, monkeypatch):
    monkeypatch.setattr("worker.dispatch.enqueue_whatsapp_delivery", lambda *args: None)
    settings.PUBLIC_BASE_URL = "https://sandbox.elmenlabs.com"
    conversation = Conversation.objects.create(
        browser_id=uuid.uuid4(), channel="whatsapp", whatsapp_sender="523312345678"
    )
    message = Message.objects.create(
        conversation=conversation,
        role="assistant",
        text="Estas opciones pueden interesarte. ¿Cuál te interesa?",
        properties=[card(id=i) for i in range(1, 5)],
    )
    queue_reply(conversation, message)
    body = conversation.whatsapp_deliveries.get().payload["text"]["body"]
    assert body.count("Ver propiedad:") == 3
    assert "/propiedades/4" not in body
    assert "localhost" not in body
    assert body.endswith("¿Cuál te interesa?")
