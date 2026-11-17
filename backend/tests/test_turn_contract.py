"""Whole-turn contracts: continuity, authorized presentation and output-only repair."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from datalayer.conversations import conversation_output, receive_message
from datalayer.models import (
    Advisor,
    AppointmentOperation,
    AppointmentProposal,
    Conversation,
    Execution,
    Message,
    Property,
    Prospect,
    WhatsAppDelivery,
)
from datalayer.replies import validate_reply
from datalayer.turns import load_turn
from datalayer.whatsapp import apply_status, queue_reply
from harness.runtime import attend
from tests.test_increment import (
    ScriptedClient,
    close_async_connections,  # noqa: F401
    new_turn,
    response,
    tool,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def home():
    return Property.objects.create(
        title="PRUEBA · Casa", operation="rent", kind="house", municipality="Zapopan",
        neighborhood="La Estancia", price=24000, published=True, accepts_pets=True,
    )


def final(text, *, pending=None, cards=None, control=None, purpose="atender la intención actual"):
    blocks = [{"kind": "text", "text": text}]
    if cards:
        blocks.append({"kind": "properties", "property_ids": cards})
    if control:
        blocks.append(control)
    return {"type": "tool_use", "id": "reply-" + uuid.uuid4().hex,
            "name": "propose_reply", "input": {
                "version": 1, "blocks": blocks,
                "continuity": {"purpose": purpose, "pending": pending},
            }}


def execute(c, *responses):
    client = ScriptedClient(list(responses))
    asyncio.run(attend(str(c.pk), client, group_messages=False))
    c.refresh_from_db()
    return client, c.messages.last()


def visit_proposal(c, prop):
    advisor = Advisor.objects.create(name="Asesor de prueba")
    start = timezone.now() + timedelta(days=2)
    return AppointmentProposal.objects.create(
        conversation=c, property=prop, advisor=advisor, action="create",
        start=start, end=start + timedelta(hours=1),
    )


def test_exploration_click_name_then_interruption_survives_reload(home, monkeypatch):
    c = new_turn("Un departamento hasta 25000")
    execute(c, response(tool({"max_price": 40000})),
            response(final("Te muestro una opción.", cards=[home.pk])))
    first = c.messages.last()
    assert [p["id"] for p in first.properties] == [home.pk]
    assert first.continuity["pending"] is None
    receive_message(c.pk, c.browser_id, "ignored", uuid.uuid4(), property_id=home.pk)

    def no_slots(*args):
        raise AssertionError("generic interest must not force a calendar query")

    monkeypatch.setattr("harness.tools.visit_tool", no_slots)
    _, named = execute(c, response(final("¿Con quién tengo el gusto?", pending={
        "kind": "name", "subject": "nombre opcional",
    })))
    assert named.text == "¿Con quién tengo el gusto?" and not named.properties
    reloaded = Conversation.objects.get(pk=c.pk)
    assert conversation_output(reloaded)["messages"][-1]["presentation"] == named.presentation
    receive_message(c.pk, c.browser_id, "Antes, ¿aceptan perros?", uuid.uuid4())
    client, interrupted = execute(c,
        response({"type": "tool_use", "id": "pets", "name": "get_property",
                  "input": {"property_id": home.pk, "show_card": False}}),
        response(final("Sí, acepta mascotas.")))
    assert "nombre opcional" in client.calls[0]["system"]
    assert interrupted.continuity["pending"] is None and not interrupted.properties
    assert c.contact_name == "" and not c.name_requested
    assert conversation_output(c)["active_control"] is None


def test_specific_date_uses_tool_without_name_or_contact_side_question(home, monkeypatch):
    c = new_turn("¿Puedo verla mañana?")
    calls = []

    def availability(cid, revision, name, args):
        calls.append(name)
        return {"options": [{"start": "2026-11-09T11:00:00-06:00"}]}

    monkeypatch.setattr("harness.tools.visit_tool", availability)
    _, reply = execute(c, response({"type": "tool_use", "id": "slots", "name": "visit_slots",
                                   "input": {"property_id": home.pk}}),
                       response(final("Tengo el lunes a las 11. ¿Te funciona?", pending={
                           "kind": "slot", "subject": "horario de visita",
                       })))
    assert calls == ["visit_slots"]
    assert reply.continuity["pending"]["kind"] == "slot"
    assert conversation_output(c)["active_control"] is None
    assert not AppointmentOperation.objects.exists()


def test_name_and_phone_together_prepare_only_the_missing_confirmation(home):
    c = new_turn("Soy Ana, el lunes a las 11 me funciona. Mi celular es 3312345678")
    c.interest_expressed = True
    c.interests.add(home)
    c.save()
    execute(c, response(
        {"type": "tool_use", "id": "name", "name": "record_name", "input": {"name": "Ana"}},
        {"type": "tool_use", "id": "phone", "name": "prepare_contact", "input": {"phone": "3312345678"}},
    ), response(final("Revisa tu número para continuar.", control={"kind": "contact"}, pending={
        "kind": "contact_confirmation", "subject": "confirmar el número declarado",
    })))
    output = conversation_output(c)
    assert c.contact_name == "Ana" and c.contact_candidate["phone"] == "+523312345678"
    assert output["active_control"] == "contact" and not output["contact_registered"]
    assert not AppointmentOperation.objects.exists() and not AppointmentProposal.objects.exists()


@pytest.mark.parametrize("truncated", [False, True])
def test_mixed_or_truncated_generation_never_executes_the_business_batch(home, truncated):
    c = new_turn("Me interesa esta casa")
    business = {"type": "tool_use", "id": "interest", "name": "record_interest",
                "input": {"property_ids": [home.pk]}}
    invalid = response(business, *([] if truncated else [final("Anotado")]),
                       stop_reason="max_tokens" if truncated else "tool_use")
    client, reply = execute(c, invalid, response(final("¿Quieres conocer sus horarios?")))
    assert not c.interest_expressed and not c.interests.exists()
    assert not reply.is_error
    assert [t["name"] for t in client.calls[-1]["tools"]] == ["propose_reply"]
    assert client.calls[-1]["tool_choice"] == {"type": "tool", "name": "propose_reply"}
    assert all(b["type"] in {"tool_result", "text"}
               for b in client.calls[-1]["messages"][-2]["content"])


def test_repair_cannot_execute_writes_even_if_model_ignores_available_tools(home):
    c = new_turn("Busco opciones")
    _, reply = execute(c,
        response(final("Una opción", cards=[home.pk])),  # no retrieval authorized this reference
        response({"type": "tool_use", "id": "interest", "name": "record_interest",
                  "input": {"property_ids": [home.pk]}}))
    assert not c.interest_expressed and not c.interests.exists()
    assert reply.continuity["pending"] is None
    assert Execution.objects.get().error_code == "reply_recovery"


def test_correcting_output_keeps_name_write_without_repeating_it():
    c = new_turn("Soy Ana")
    client, reply = execute(c,
        response({"type": "tool_use", "id": "name", "name": "record_name", "input": {"name": "Ana"}}),
        response(final("¿Con quién tengo el gusto?", pending={"kind": "name", "subject": "nombre"})),
        response(final("Ana, ¿buscas comprar o rentar?", pending={"kind": "clarification", "subject": "operación"})))
    assert c.contact_name == "Ana" and not reply.is_error and len(client.calls) == 3
    assert [e["tool"] for e in Execution.objects.get().tool_events].count("record_name") == 1


def test_existing_visit_proposal_is_not_attached_to_an_unrelated_reply(home, monkeypatch):
    monkeypatch.setattr("worker.dispatch.enqueue_whatsapp_delivery", lambda *args: None)
    prospect = Prospect.objects.create(phone="+523312345678")
    c = new_turn("Antes, ¿acepta mascotas?")
    c.channel, c.whatsapp_sender, c.declared_phone, c.prospect = "whatsapp", "523312345678", prospect.phone, prospect
    c.save()
    visit_proposal(c, home)
    execute(c, response(final("Sí, acepta mascotas.")))
    delivery = WhatsAppDelivery.objects.get()
    assert delivery.payload["type"] == "text"
    assert conversation_output(c)["messages"][-1]["role"] == "user"  # queued reply is not public
    assert load_turn(c.pk) is None  # already answered; delivery does not re-run the agent
    delivery.status = "sent"
    delivery.save()
    assert conversation_output(c)["active_control"] is None
    acknowledgement = Message.objects.create(
        conversation=c, role="assistant", text="No te enviaré más seguimientos."
    )
    assert queue_reply(c, acknowledgement).payload["type"] == "text"


def test_visit_control_must_reference_own_current_proposal(home):
    c = new_turn("Confirmemos")
    prospect = Prospect.objects.create(phone="+523312345678")
    c.prospect, c.declared_phone = prospect, prospect.phone
    c.save()
    own = visit_proposal(c, home)
    other = new_turn("Otra conversación")
    foreign = visit_proposal(other, home)
    with pytest.raises(ValueError):
        validate_reply(c.pk, c.revision, final("Confirma aquí", control={
            "kind": "visit", "proposal_id": str(foreign.pk),
        }, pending={"kind": "visit_confirmation", "subject": "visita"})["input"], [])
    execute(c, response(final("Confirma aquí", control={"kind": "visit", "proposal_id": str(own.pk)},
                              pending={"kind": "visit_confirmation", "subject": "visita"})))
    assert conversation_output(c)["active_proposal_id"] == own.pk
    assert not AppointmentOperation.objects.exists()


def test_whatsapp_continuity_requires_observable_acceptance_and_ignores_late_callbacks(monkeypatch):
    monkeypatch.setattr("worker.dispatch.enqueue_whatsapp_delivery", lambda *args: None)
    c = Conversation.objects.create(channel="whatsapp", whatsapp_sender="523312345678", revision=1)
    Message.objects.create(conversation=c, role="user", text="Hola")
    _, first = execute(c, response(final("¿Con quién tengo el gusto?", pending={"kind": "name", "subject": "nombre"})))
    delivery = WhatsAppDelivery.objects.get(message=first)
    c.revision += 1
    c.save()
    Message.objects.create(conversation=c, role="user", text="Antes dime si hay casas")
    assert load_turn(c.pk)["continuity"] is None
    delivery.status, delivery.provider_id = "sent", "provider-first"
    delivery.save()
    assert load_turn(c.pk)["continuity"]["pending"]["kind"] == "name"
    _, second = execute(c, response(final("¿En qué zona buscas?", pending={"kind": "clarification", "subject": "zona"})))
    later = WhatsAppDelivery.objects.get(message=second)
    later.status = "sent"
    later.save()
    with transaction.atomic():
        apply_status({"id": "provider-first", "status": "read", "recipient_id": c.whatsapp_sender})
    c.revision += 1
    c.save()
    Message.objects.create(conversation=c, role="user", text="Zapopan")
    assert load_turn(c.pk)["continuity"]["pending"]["subject"] == "zona"


def test_structured_whatsapp_keeps_order_and_rejects_overflow_without_truncating(monkeypatch):
    monkeypatch.setattr("worker.dispatch.enqueue_whatsapp_delivery", lambda *args: None)
    c = Conversation.objects.create(channel="whatsapp", whatsapp_sender="523312345678", revision=1)
    oversized = final("x" * 2500)["input"]
    oversized["blocks"].append({"kind": "text", "text": "y" * 2500})
    with pytest.raises(ValueError):
        validate_reply(c.pk, 1, oversized, [])
    msg = Message.objects.create(conversation=c, role="assistant", text="Uno\n\nDos",
                                 presentation=[{"kind": "text", "text": "Uno"}, {"kind": "text", "text": "Dos"}])
    assert queue_reply(c, msg).payload["text"]["body"] == "Uno\n\nDos"


def test_closing_has_no_pending_or_active_control():
    c = new_turn("No quiero compartir mi nombre. Gracias, hasta luego")
    _, reply = execute(c, response(final("Gracias a ti. Aquí seguimos cuando lo necesites.")))
    assert reply.continuity["pending"] is None and not c.contact_name
    assert conversation_output(c)["active_control"] is None


def test_generic_interest_requires_tool_protocol_instead_of_user_fallback(home):
    """A provider may answer as free text unless the request requires tool use."""
    c = new_turn("Busco un depa que acepte mascotas hasta 35000 en Zapopan")
    execute(c, response(tool({"max_price": 35000})),
            response(final("Encontré una opción.", cards=[home.pk])))
    receive_message(c.pk, c.browser_id, "ignored", uuid.uuid4(), property_id=home.pk)

    class ToolChoiceClient(ScriptedClient):
        async def create(self, **kwargs):
            if kwargs.get("tool_choice", {}).get("type") in {"any", "tool"}:
                self.responses = iter([response(final("Claro. ¿Con quién tengo el gusto?", pending={
                    "kind": "name", "subject": "nombre opcional",
                }))])
            else:
                self.responses = iter([response({"type": "text", "text":
                    "Claro. ¿Con quién tengo el gusto?"}, raw=True)])
            return await super().create(**kwargs)

    client = ToolChoiceClient([])
    asyncio.run(attend(str(c.pk), client, group_messages=False))
    reply = c.messages.last()
    assert reply.text != "Tu mensaje quedó guardado. No pude preparar la respuesta; puedes seguir escribiéndome."
    assert reply.text == "Claro. ¿Con quién tengo el gusto?"
    assert len(client.calls) == 1
    assert Execution.objects.filter(conversation=c).last().error_code == ""


@pytest.mark.parametrize("failure,reason", [
    ("text", "missing_final_tool"),
    ("card", "unauthorized_card"),
    ("visit", "visit_unavailable"),
])
def test_rejection_trace_identifies_failure_without_recording_reply_text(home, failure, reason):
    c = new_turn("Me interesa una visita")
    private_copy = "COPY_NOT_FOR_DIAGNOSTICS"
    if failure == "text":
        invalid = response({"type": "text", "text": private_copy}, raw=True)
    elif failure == "card":
        invalid = response(final(private_copy, cards=[home.pk]))
    else:
        invalid = response(final(private_copy,
                                 control={"kind": "visit", "proposal_id": str(uuid.uuid4())},
                                 pending={"kind": "visit_confirmation", "subject": "visita"}))
    execute(c, invalid, invalid)
    execution = Execution.objects.filter(conversation=c).last()
    assert execution.error_code == "reply_recovery"
    assert [e["reason"] for e in execution.tool_events] == [reason, reason]
    assert all("stop_reason" in e for e in execution.tool_events)
    assert private_copy not in str(execution.tool_events)
