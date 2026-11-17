import asyncio
import os
import re
import uuid
from pathlib import Path

import pytest
from django.utils import timezone

from datalayer.models import Conversation, FollowupCycle, Message, Notification, Property, Prospect
from datalayer.prospects import prepare_contact
from datalayer.tool_actions import apply_tool
from datalayer.turns import load_turn
from harness.runtime import attend
from tests.test_increment import close_async_connections  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_whatsapp_name_updates_crm_without_interest_or_permission_changes():
    prospect = Prospect.objects.create(phone="+523312345678", contact_opted_out=True)
    c = Conversation.objects.create(
        channel="whatsapp",
        whatsapp_sender="523312345678",
        prospect=prospect,
        followup_permission=False,
        revision=1,
    )
    result = apply_tool(c.pk, 1, "record_name", {"name": " Guillermo "})
    c.refresh_from_db()
    prospect.refresh_from_db()
    assert result == {"recorded": True, "name": "Guillermo"}
    assert c.contact_name == prospect.name == "Guillermo"
    assert (
        not c.interest_expressed and prospect.contact_opted_out and c.followup_permission is False
    )
    assert not FollowupCycle.objects.exists() and not Notification.objects.exists()
    assert load_turn(c.pk)["contact_name"] == "Guillermo"


def test_anonymous_website_name_stays_in_its_session_and_prefills_contact():
    c = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1, interest_expressed=True)
    apply_tool(c.pk, 1, "record_name", {"name": "Ana"})
    c.refresh_from_db()
    assert c.contact_name == "Ana" and not Prospect.objects.exists()
    prepare_contact(c, {"phone": "+523312345678"})
    c.refresh_from_db()
    assert c.contact_candidate["name"] == "Ana"
    apply_tool(c.pk, 1, "record_name", {"name": "María"})
    c.refresh_from_db()
    assert c.contact_candidate["name"] == "María"


def test_declared_browser_phone_does_not_authorize_shared_crm_name_edits():
    prospect = Prospect.objects.create(phone="+523312345678", name="Nombre del CRM")
    c = Conversation.objects.create(
        browser_id=uuid.uuid4(), prospect=prospect, declared_phone=prospect.phone, revision=1
    )
    assert load_turn(c.pk)["contact_name"] == ""
    apply_tool(c.pk, 1, "record_name", {"name": "Nombre declarado"})
    prospect.refresh_from_db()
    assert prospect.name == "Nombre del CRM"
    assert load_turn(c.pk)["contact_name"] == "Nombre declarado"


def test_whatsapp_uses_existing_crm_name_and_interest_retains_explicit_name():
    prospect = Prospect.objects.create(phone="+523312345678", name="Guillermo")
    c = Conversation.objects.create(
        channel="whatsapp",
        whatsapp_sender="523312345678",
        prospect=prospect,
        declared_phone=prospect.phone,
        revision=1,
    )
    assert load_turn(c.pk)["contact_name"] == "Guillermo"
    apply_tool(c.pk, 1, "record_interest", {"name": "Memo", "property_ids": []})
    c.refresh_from_db()
    prospect.refresh_from_db()
    assert c.contact_name == prospect.name == "Memo"


@pytest.mark.skipif(
    os.getenv("MAIA_LIVE_HAIKU_CHECK") != "1", reason="API real de Haiku, sin envíos WhatsApp"
)
def test_real_haiku_handles_interest_interruption_and_name_without_sending(monkeypatch):
    from agent.config import AGENT_DIR
    from datalayer.inventory import public_property
    from datalayer.models import Execution, WhatsAppDelivery

    assert AGENT_DIR.parent.resolve() == Path(__file__).resolve().parents[1]

    monkeypatch.setattr("worker.dispatch.enqueue_whatsapp_delivery", lambda *args: None)
    prospect = Prospect.objects.create(phone="+523312345678", contact_opted_out=True)
    prop = Property.objects.create(
        title="PRUEBA · Departamento",
        reference="PRUEBA-NOMBRE",
        operation="rent",
        kind="apartment",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=24000,
        accepts_pets=True,
        published=True,
    )
    c = Conversation.objects.create(
        channel="whatsapp",
        whatsapp_sender="523312345678",
        prospect=prospect,
        declared_phone=prospect.phone,
        followup_permission=False,
        revision=1,
        last_whatsapp_at=timezone.now(),
    )
    Message.objects.create(conversation=c, role="user", text="Busco un departamento en La Estancia")
    Message.objects.create(conversation=c, role="assistant", text="Te muestro esta opción.",
                           properties=[public_property(prop)])
    Message.objects.create(conversation=c, role="user", text="Hola, me interesa este departamento.")
    asyncio.run(attend(str(c.pk), group_messages=False))
    first = c.messages.filter(role="assistant").last()
    assert first and not first.is_error
    assert first.presentation and first.continuity["purpose"]
    assert not first.properties  # the already presented card is not duplicated
    assert not re.search(r"a qué (?:número|celular)|cuál es tu (?:número|celular)", first.text, re.IGNORECASE)
    # Simulate provider acceptance locally; enqueue is disabled and no HTTP send occurs.
    WhatsAppDelivery.objects.filter(message=first).update(status="sent", provider_id="test-first")
    c.refresh_from_db()
    c.revision += 1
    c.save()
    Message.objects.create(conversation=c, role="user", text="Antes, ¿acepta mascotas?")
    asyncio.run(attend(str(c.pk), group_messages=False))
    interrupted = c.messages.filter(role="assistant").last()
    assert interrupted and not interrupted.is_error and not interrupted.properties
    assert interrupted.text.strip()
    assert not re.search(r"cómo te llamas|cuál es tu nombre|con quién tengo", interrupted.text, re.IGNORECASE)
    assert interrupted.continuity["pending"] is None or interrupted.continuity["pending"]["kind"] != "name"
    WhatsAppDelivery.objects.filter(message=interrupted).update(status="sent", provider_id="test-interruption")
    c.refresh_from_db()
    c.revision += 1
    c.save()
    Message.objects.create(conversation=c, role="user", text="Me llamo Guillermo")
    asyncio.run(attend(str(c.pk), group_messages=False))
    c.refresh_from_db()
    prospect.refresh_from_db()
    assert c.contact_name == prospect.name == "Guillermo"
    assert not c.messages.filter(role="assistant", is_error=True).exists()
    assert not Execution.objects.filter(conversation=c).exclude(status="completed", error_code="").exists()
    assert not re.search(
        r"cómo te llamas|cuál es tu nombre|con quién tengo", c.messages.last().text, re.IGNORECASE
    )
    assert (
        prospect.contact_opted_out
        and c.followup_permission is False
        and not FollowupCycle.objects.filter(permission=True, closed_at__isnull=True).exists()
    )
    assert not WhatsAppDelivery.objects.exclude(status__in=["queued", "sent"]).exists()
