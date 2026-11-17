import asyncio
import json
import uuid

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from datalayer.conversations import receive_message
from datalayer.models import (
    Advisor,
    Conversation,
    Execution,
    Message,
    Notification,
    Property,
    Prospect,
    User,
)
from datalayer.prospects import (
    confirm_contact,
    normalize_phone,
    prepare_contact,
    record_interest,
    update_prospect,
)
from datalayer.schemas import ConfirmContactInput, ProspectUpdate
from datalayer.tool_actions import apply_tool
from datalayer.turns import load_turn
from harness.memory.context import build_messages
from harness.runtime import attend
from tests.test_increment import ScriptedClient, browser, close_async_connections, post, response  # noqa: F401
from worker.telegram import deliver_notification

pytestmark = pytest.mark.django_db(transaction=True)
PHONE = "+523312345678"


@pytest.fixture(autouse=True)
def isolate_jobs():
    # Procrastinate owns unmanaged tables, so Django's normal flush does not clear them.
    assert connection.settings_dict["NAME"].startswith("test_")
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE procrastinate_jobs RESTART IDENTITY CASCADE")


@pytest.fixture
def advisor():
    return Advisor.objects.create(name="PRUEBA · Asesor", is_default=True, telegram_chat_id="12345")


@pytest.fixture
def prop(advisor):
    return Property.objects.create(
        title="PRUEBA · Casa",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=32000,
        published=True,
        advisor=advisor,
    )


def conversation_for_browser():
    client, headers = browser()
    result = post(client, "/api/conversations", {}, headers)
    assert result.status_code == 200
    return client, headers, Conversation.objects.get(pk=result.json()["id"])


def register(conversation, property_ids=(), phone=PHONE, human=False):
    with transaction.atomic():
        record_interest(
            conversation, {"property_ids": list(property_ids), "human_requested": human}
        )
        prepare_contact(conversation, {"phone": phone, "name": "PRUEBA · Visitante"})
    return confirm_contact(
        conversation.pk,
        conversation.browser_id,
        ConfirmContactInput(phone=phone, name="PRUEBA · Visitante", confirmed=True),
    )


def update_data(prospect, **changes):
    return ProspectUpdate.model_validate(
        {
            "name": prospect.name,
            "advisor_id": prospect.advisor_id,
            "status": prospect.status,
            "criteria": prospect.criteria,
            "next_step": prospect.next_step,
            "automation_paused": prospect.automation_paused,
            **changes,
        }
    )


def staff_browser():
    client, headers = browser()
    user = User.objects.create_user(
        f"{uuid.uuid4()}@example.test", "prueba-password-123", is_staff=True
    )
    result = post(
        client, "/api/auth/login", {"email": user.email, "password": "prueba-password-123"}, headers
    )
    assert result.status_code == 200
    return client, {"HTTP_X_CSRFTOKEN": result.json()["csrf_token"]}, user


def test_phone_normalization_and_invalid_input():
    assert normalize_phone("33 1234 5678") == PHONE
    assert normalize_phone("+52 (33) 1234-5678") == PHONE
    with pytest.raises(ValidationError):
        normalize_phone("12345")


def test_general_interest_without_chosen_property_can_register_contact(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    conversation = register(conversation)
    assert Prospect.objects.get().advisor_id == advisor.pk
    assert conversation.interest_expressed


def test_registered_contact_cannot_be_reopened_by_another_tool_call(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    conversation = register(conversation)
    result = apply_tool(conversation.pk, conversation.revision, "prepare_contact", {"phone": PHONE})
    conversation.refresh_from_db()
    assert result["contact_registered"] and not conversation.contact_candidate


def test_contact_requires_interest_explicit_confirmation_and_deduplicates(prop):
    client, headers, conversation = conversation_for_browser()
    base = f"/api/conversations/{conversation.pk}/contact"
    assert post(client, base + "/prepare", {"phone": PHONE}, headers).status_code == 409
    with transaction.atomic():
        record_interest(conversation, {"property_ids": [prop.pk]})
    assert post(client, base + "/prepare", {"phone": "12345"}, headers).status_code == 422
    pending = post(client, base + "/prepare", {"phone": "33 1234 5678"}, headers)
    assert pending.status_code == 200 and not Prospect.objects.exists()
    assert pending.json()["pending_contact"]["phone"] == PHONE
    assert (
        post(client, base + "/confirm", {"phone": PHONE, "confirmed": False}, headers).status_code
        == 422
    )
    assert (
        post(
            client, base + "/confirm", {"phone": "+525555555555", "confirmed": True}, headers
        ).status_code
        == 422
    )
    first = post(client, base + "/confirm", {"phone": PHONE, "confirmed": True}, headers)
    assert first.status_code == 200 and first.json()["contact_registered"]
    assert Prospect.objects.get().advisor_id == prop.advisor_id
    assert "prospect_id" not in first.json() and "status" not in first.json()
    messages, events = Message.objects.count(), Notification.objects.count()
    assert (
        post(client, base + "/confirm", {"phone": PHONE, "confirmed": True}, headers).status_code
        == 200
    )
    assert (
        Prospect.objects.count() == 1
        and Message.objects.count() == messages
        and Notification.objects.count() == events
    )


def test_first_property_owner_default_owner_and_existing_contact_isolation(prop, advisor):
    other_advisor = Advisor.objects.create(name="PRUEBA · Otro", telegram_chat_id="23456")
    second = Property.objects.create(
        title="PRUEBA · Segunda",
        operation="sale",
        kind="house",
        municipality="Zapopan",
        neighborhood="Centro",
        price=999999,
        published=True,
        advisor=other_advisor,
    )
    first_client, _, first = conversation_for_browser()
    first.criteria = {"max_price": "40000"}
    first.save()
    first = register(first, [second.pk, prop.pk])
    lead = Prospect.objects.get()
    assert lead.advisor_id == other_advisor.pk
    lead.status = "attending"
    lead.next_step = "Dato privado del asesor"
    lead.save()
    Message.objects.create(conversation=first, role="assistant", text="HISTORIAL PRIVADO ANTERIOR")
    other_client, _, other = conversation_for_browser()
    other.criteria = {"max_price": "80000"}
    other.save()
    other = register(other, [prop.pk])
    lead.refresh_from_db()
    assert Prospect.objects.count() == 1 and lead.advisor_id == other_advisor.pk
    assert lead.status == "attending" and lead.criteria == {"max_price": "40000"}
    assert other_client.get(f"/api/conversations/{first.pk}").status_code == 404
    assert first_client.get(f"/api/conversations/{other.pk}").status_code == 404
    public = other_client.get(f"/api/conversations/{other.pk}").json()
    assert "HISTORIAL PRIVADO" not in json.dumps(public) and "Dato privado" not in json.dumps(
        public
    )
    turn = load_turn(other.pk)
    assert "HISTORIAL PRIVADO" not in json.dumps(turn)
    general = Conversation.objects.create(browser_id=uuid.uuid4())
    with transaction.atomic():
        record_interest(general, {"human_requested": True})
    assert general.advisor_id == advisor.pk


def test_anonymous_human_request_visible_in_crm_and_queued_once(advisor):
    _, _, conversation = conversation_for_browser()
    with transaction.atomic():
        for _ in range(2):
            record_interest(
                conversation, {"human_requested": True, "summary": "No desea compartir celular."}
            )
    assert not Prospect.objects.exists() and Notification.objects.count() == 1
    assert Notification.objects.get().advisor_id == advisor.pk
    staff, _, _ = staff_browser()
    request = staff.get("/api/crm/requests").json()[0]
    assert request["phone"] == "" and request["human_requested"] and request["prospect_id"] is None
    guest, _ = browser()
    assert guest.get("/api/crm/requests").status_code == 401


def test_pending_human_request_deduplicates_until_advisor_acknowledges(prop):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    conversation = register(conversation, [prop.pk], human=True)
    receive_message(conversation.pk, conversation.browser_id, "Confirmo mis datos.", uuid.uuid4())
    conversation.refresh_from_db()
    apply_tool(conversation.pk, conversation.revision, "record_interest", {"human_requested": True})
    assert Notification.objects.filter(reason="human_request").count() == 1
    lead = Prospect.objects.get()
    update_prospect(lead.pk, update_data(lead, status="attending"), None)
    receive_message(
        conversation.pk,
        conversation.browser_id,
        "Quiero hablar otra vez con el asesor.",
        uuid.uuid4(),
    )
    conversation.refresh_from_db()
    apply_tool(conversation.pk, conversation.revision, "record_interest", {"human_requested": True})
    assert Notification.objects.filter(reason="human_request").count() == 2


def test_staff_settings_permissions_default_and_private_chat_validation(advisor):
    guest, headers = browser()
    for path in ["advisors", "prospects", "configuration"]:
        assert guest.get("/api/crm/" + path).status_code == 401
    assert post(guest, "/api/crm/advisors", {"name": "Intruso"}, {}).status_code == 403
    staff, headers, _ = staff_browser()
    assert (
        post(
            staff, "/api/crm/advisors", {"name": "PRUEBA", "telegram_chat_id": "-12345"}, headers
        ).status_code
        == 422
    )
    saved = post(
        staff,
        "/api/crm/advisors",
        {"name": "PRUEBA · Nuevo", "is_default": True, "whatsapp": "+523312345678"},
        headers,
    )
    assert saved.status_code == 200
    assert saved.json()["whatsapp"] == "+523312345678"
    assert Advisor.objects.get(pk=saved.json()["id"]).whatsapp == "+523312345678"
    assert (
        post(
            staff,
            "/api/crm/advisors",
            {"name": "Inválido", "whatsapp": "javascript:alert(1)"},
            headers,
        ).status_code
        == 422
    )
    assert Advisor.objects.filter(is_default=True).count() == 1
    advisor.refresh_from_db()
    assert not advisor.is_default
    assert isinstance(staff.get("/api/crm/configuration").json()["telegram_configured"], bool)


def test_staff_can_read_and_update_all_prospect_fields_through_crm_api(prop):
    guest, _, conversation = conversation_for_browser()
    conversation = register(conversation, [prop.pk])
    lead = Prospect.objects.get()
    staff, headers, user = staff_browser()
    path = f"/api/crm/prospects/{lead.pk}"
    detail = staff.get(path)
    assert detail.status_code == 200
    assert detail.json()["conversations"][0]["phone"] == PHONE
    assert staff.get("/api/crm/prospects").json()[0]["id"] == lead.pk
    other = Advisor.objects.create(name="PRUEBA · Responsable actualizado")
    payload = update_data(
        lead,
        name="PRUEBA · Nombre corregido",
        advisor_id=other.pk,
        status="attending",
        next_step="Llamar para resolver dudas.",
        criteria={"max_price": 35000},
        automation_paused=True,
    ).model_dump(mode="json")
    result = staff.put(path, data=json.dumps(payload), content_type="application/json", **headers)
    assert result.status_code == 200
    updated = result.json()
    assert (
        updated["advisor_id"] == other.pk
        and updated["status"] == "attending"
        and updated["automation_paused"]
    )
    assert (
        updated["next_step"] == "Llamar para resolver dudas."
        and updated["criteria"]["max_price"] == "35000"
    )
    assert updated["events"][0]["actor"] == user.email
    public = guest.get(f"/api/conversations/{conversation.pk}").json()
    assert public["automation_paused"] and "status" not in public and "advisor_id" not in public
    assert "Llamar para resolver" not in json.dumps(public)


def test_commercial_state_does_not_pause_and_pause_blocks_messages(prop):
    _, _, conversation = conversation_for_browser()
    conversation = register(conversation, [prop.pk])
    lead = Prospect.objects.get()
    update_prospect(lead.pk, update_data(lead, status="attending"), None)
    lead.refresh_from_db()
    assert not lead.automation_paused
    update_prospect(lead.pk, update_data(lead, automation_paused=True), None)
    receive_message(conversation.pk, conversation.browser_id, "¿Me puedes responder?", uuid.uuid4())
    before = Message.objects.filter(role="assistant").count()
    asyncio.run(attend(str(conversation.pk), ScriptedClient([]), group_messages=False))
    assert Message.objects.filter(role="assistant").count() == before
    assert Notification.objects.filter(reason="paused_message").count() == 1
    assert conversation.messages.filter(text="¿Me puedes responder?").exists()
    lead.refresh_from_db()
    update_prospect(lead.pk, update_data(lead, automation_paused=False), None)
    receive_message(conversation.pk, conversation.browser_id, "Ahora sí", uuid.uuid4())
    asyncio.run(
        attend(
            str(conversation.pk),
            ScriptedClient([response({"type": "text", "text": "Aquí estoy."})]),
            group_messages=False,
        )
    )
    assert conversation.messages.last().text == "Aquí estoy."


def test_pause_during_model_call_invalidates_output(prop):
    _, _, conversation = conversation_for_browser()
    conversation = register(conversation, [prop.pk])
    lead = Prospect.objects.get()

    async def pause_while_waiting():
        await sync_to_async(update_prospect)(
            lead.pk, update_data(lead, automation_paused=True), None
        )
        return response({"type": "text", "text": "ESTA RESPUESTA NO DEBE SALIR"})

    asyncio.run(
        attend(str(conversation.pk), ScriptedClient([pause_while_waiting]), group_messages=False)
    )
    assert not conversation.messages.filter(role="assistant").exists()
    assert Execution.objects.get().status == "superseded"


def test_interest_tool_rejects_unpublished_properties(prop):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    prop.published = False
    prop.save()
    assert (
        apply_tool(conversation.pk, 0, "record_interest", {"property_ids": [prop.pk]})["error"]
        == "property_not_available"
    )
    assert not conversation.interests.exists() and not Notification.objects.exists()


def test_turn_keeps_ordered_card_references_without_private_fields(prop):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1)
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        text="Estas son tus opciones.",
        properties=[
            {
                "id": prop.pk,
                "reference": prop.reference,
                "title": prop.title,
                "internal_notes": "PRIVADO: no incluir",
            }
        ],
    )
    Message.objects.create(conversation=conversation, role="user", text="Me interesa la primera.")
    turn = load_turn(conversation.pk)
    assert prop.reference in build_messages(turn)[0]["content"]
    assert "PRIVADO" not in json.dumps(turn)


def test_explicit_phone_is_prepared_from_current_messages_without_waiting_for_model(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1)
    Message.objects.create(
        conversation=conversation, role="user", text="Quiero un asesor. Mi celular es 3312345678."
    )
    result = apply_tool(
        conversation.pk, 1, "record_interest", {"human_requested": True, "name": "PRUEBA"}
    )
    conversation.refresh_from_db()
    assert result["pending_confirmation"] and conversation.contact_candidate == {
        "phone": PHONE,
        "name": "PRUEBA",
    }
    assert not Prospect.objects.exists()


def test_later_phone_message_prepares_confirmation_before_llm_processing(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    with transaction.atomic():
        record_interest(conversation, {"human_requested": True})
    Message.objects.create(
        conversation=conversation, role="assistant", text="¿A qué celular te contactamos?"
    )
    receive_message(conversation.pk, conversation.browser_id, "3312345678", uuid.uuid4())
    conversation.refresh_from_db()
    assert conversation.contact_candidate["phone"] == PHONE and not Prospect.objects.exists()


def test_phone_candidates_ignore_other_context_and_ambiguous_numbers(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1)
    Message.objects.create(conversation=conversation, role="user", text="Mi celular es 3312345678.")
    Message.objects.create(
        conversation=conversation, role="assistant", text="Seguimos conversando."
    )
    Message.objects.create(
        conversation=conversation, role="user", text="Mi presupuesto es 3312345678 pesos."
    )
    apply_tool(conversation.pk, 1, "record_interest", {"human_requested": True})
    conversation.refresh_from_db()
    assert not conversation.contact_candidate
    Message.objects.create(
        conversation=conversation,
        role="user",
        text="Mi celular es 3312345678 y mi teléfono es 3312345679.",
    )
    apply_tool(conversation.pk, 1, "record_interest", {"human_requested": True})
    conversation.refresh_from_db()
    assert not conversation.contact_candidate


def test_original_conversation_updates_requirements_until_staff_overrides(prop):
    _, _, conversation = conversation_for_browser()
    conversation = register(conversation, [prop.pk])
    lead = Prospect.objects.get()
    apply_tool(
        conversation.pk,
        conversation.revision,
        "search_properties",
        {"criteria_patch": {"max_price": 42000}},
    )
    lead.refresh_from_db()
    assert lead.criteria["max_price"] == "42000"
    update_prospect(lead.pk, update_data(lead, criteria={"max_price": 35000}), None)
    apply_tool(
        conversation.pk,
        conversation.revision,
        "search_properties",
        {"criteria_patch": {"max_price": 50000}},
    )
    lead.refresh_from_db()
    assert lead.criteria["max_price"] == "35000" and lead.criteria_source_id is None


def test_existing_anonymous_pause_remains_visible_and_can_be_lifted_after_capture(advisor):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), automation_paused=True)
    conversation = register(conversation, human=True)
    staff, headers, _ = staff_browser()
    detail = staff.get(f"/api/crm/conversations/{conversation.pk}").json()
    assert detail["conversation_paused"] and detail["automation_paused"]
    result = staff.put(
        f"/api/crm/conversations/{conversation.pk}/pause",
        data=json.dumps({"automation_paused": False}),
        content_type="application/json",
        **headers,
    )
    assert result.status_code == 200 and not result.json()["automation_paused"]


def test_harness_registers_interest_and_prepares_phone_without_creating_prospect(prop):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1)
    Message.objects.create(
        conversation=conversation,
        role="user",
        text=f"Me interesa la propiedad {prop.pk}. Mi celular es 3312345678.",
    )
    client = ScriptedClient(
        [
            response(
                {
                    "type": "tool_use",
                    "id": "i",
                    "name": "record_interest",
                    "input": {"property_ids": [prop.pk]},
                }
            ),
            response(
                {
                    "type": "tool_use",
                    "id": "c",
                    "name": "prepare_contact",
                    "input": {"phone": "3312345678"},
                }
            ),
            response(
                {
                    "type": "text",
                    "text": "Revisa tu número y confírmalo aquí. Puedes seguir conversando en el website.",
                }
            ),
        ]
    )
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    conversation.refresh_from_db()
    assert conversation.contact_candidate["phone"] == PHONE and not Prospect.objects.exists()
    assert Execution.objects.get().status == "completed"


def event_for(conversation, advisor):
    return Notification.objects.create(
        conversation=conversation,
        advisor=advisor,
        event_key=str(uuid.uuid4()),
        reason="human_request",
        summary="PRUEBA · Solicita asesor",
    )


def test_interest_click_preserves_opt_out_and_paused_conversation(prop):
    from django.utils import timezone

    from datalayer.models import FollowupCycle

    prospect = Prospect.objects.create(phone=PHONE, contact_opted_out=True)
    conversation = Conversation.objects.create(
        browser_id=uuid.uuid4(),
        prospect=prospect,
        declared_phone=PHONE,
        followup_permission=False,
        automation_paused=True,
    )
    FollowupCycle.objects.create(
        prospect=prospect,
        conversation=conversation,
        started_at=timezone.now(),
        closed_at=timezone.now(),
        reason="opted_out",
        permission=False,
    )
    receive_message(
        conversation.pk,
        conversation.browser_id,
        "Me interesa",
        uuid.uuid4(),
        property_id=prop.pk,
    )
    prospect.refresh_from_db()
    conversation.refresh_from_db()
    assert prospect.contact_opted_out and conversation.followup_permission is False
    assert not FollowupCycle.objects.filter(closed_at__isnull=True).exists()
    assert FollowupCycle.objects.count() == 1
    assert conversation.interest_expressed and conversation.automation_paused
    assert conversation.revision == conversation.answered_revision
    assert not Execution.objects.exists()
    assert not conversation.human_requested


def test_unconfigured_telegram_keeps_event(settings, advisor):
    settings.TELEGRAM_BOT_TOKEN = ""
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), advisor=advisor)
    event = event_for(conversation, advisor)
    deliver_notification(event.pk)
    event.refresh_from_db()
    assert event.status == "blocked" and event.attempts == 0


def test_late_default_configuration_persists_responsible_advisor_in_crm(settings, advisor):
    settings.TELEGRAM_BOT_TOKEN = ""
    lead = Prospect.objects.create(phone=PHONE)
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), prospect=lead)
    event = event_for(conversation, advisor)
    deliver_notification(event.pk)
    lead.refresh_from_db()
    assert lead.advisor_id == advisor.pk


def test_telegram_success_is_not_duplicated_and_payload_is_complete(settings, advisor, caplog):
    settings.TELEGRAM_BOT_TOKEN = "test-secret-never-log"
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), advisor=advisor)
    event = event_for(conversation, advisor)
    sent = []

    def transport(request):
        assert not connection.in_atomic_block
        if request.url.path.endswith("getChat"):
            return httpx.Response(
                200, json={"ok": True, "result": {"type": "private", "id": 12345}}
            )
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 81}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        deliver_notification(event.pk, client)
        deliver_notification(event.pk, client)
    event.refresh_from_db()
    assert len(sent) == 1 and event.status == "sent" and event.telegram_message_id == "81"
    assert (
        "no proporcionado" not in sent[0]["text"]
        and f"conversation={conversation.pk}" in sent[0]["text"]
    )
    assert "test-secret-never-log" not in caplog.text


def test_uncertain_delivery_never_retries(settings, advisor):
    settings.TELEGRAM_BOT_TOKEN = "test-secret"
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), advisor=advisor)
    event = event_for(conversation, advisor)
    sent = []

    def transport(request):
        if request.url.path.endswith("getChat"):
            return httpx.Response(
                200, json={"ok": True, "result": {"type": "private", "id": 12345}}
            )
        sent.append(True)
        raise httpx.ReadTimeout("provider accepted but confirmation lost", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        deliver_notification(event.pk, client)
        deliver_notification(event.pk, client)
    event.refresh_from_db()
    assert event.status == "uncertain" and len(sent) == 1
    staff, headers, _ = staff_browser()
    assert post(staff, f"/api/crm/notifications/{event.pk}/retry", {}, headers).status_code == 409


def test_group_is_rejected_before_transmitting_customer_data(settings, advisor):
    settings.TELEGRAM_BOT_TOKEN = "test-secret"
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), advisor=advisor)
    event = event_for(conversation, advisor)
    paths = []

    def transport(request):
        paths.append(request.url.path.split("/")[-1])
        return httpx.Response(200, json={"ok": True, "result": {"type": "group", "id": 12345}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        deliver_notification(event.pk, client)
    event.refresh_from_db()
    assert (
        paths == ["getChat"]
        and event.status == "failed"
        and event.error_code == "private_chat_required"
    )


def test_confirm_rolls_back_if_notification_cannot_be_queued(prop, monkeypatch):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    with transaction.atomic():
        record_interest(conversation, {"property_ids": [prop.pk]})
        prepare_contact(conversation, {"phone": PHONE})

    def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("worker.dispatch.enqueue_notification", fail)
    with pytest.raises(RuntimeError):
        confirm_contact(
            conversation.pk,
            conversation.browser_id,
            ConfirmContactInput(phone=PHONE, confirmed=True),
        )
    conversation.refresh_from_db()
    assert (
        not Prospect.objects.exists()
        and not Notification.objects.exists()
        and conversation.prospect_id is None
    )


@pytest.mark.parametrize("status", ["new", "attending", "not_interested"])
def test_manual_commercial_stages_preserve_contact_and_do_not_pause_maia(prop, status):
    conversation = register(Conversation.objects.create(browser_id=uuid.uuid4()), [prop.pk])
    lead = Prospect.objects.get()
    staff, headers, _ = staff_browser()
    payload = update_data(lead, status=status).model_dump(mode="json")
    result = staff.put(
        f"/api/crm/prospects/{lead.pk}",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    assert result.status_code == 200
    assert result.json()["status"] == status and not result.json()["automation_paused"]
    lead.refresh_from_db()
    assert (
        lead.phone == PHONE
        and lead.advisor_id == prop.advisor_id
        and lead.conversations.filter(pk=conversation.pk).exists()
    )


def test_known_rejection_can_be_retried_through_crm_without_duplicate_delivery(settings, advisor):
    settings.TELEGRAM_BOT_TOKEN = "test-secret"
    event = event_for(
        Conversation.objects.create(browser_id=uuid.uuid4(), advisor=advisor), advisor
    )
    attempts = []

    def transport(request):
        if request.url.path.endswith("getChat"):
            return httpx.Response(
                200, json={"ok": True, "result": {"type": "private", "id": 12345}}
            )
        attempts.append(True)
        if len(attempts) == 1:
            return httpx.Response(400, json={"ok": False, "error_code": 400})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        deliver_notification(event.pk, client)
        event.refresh_from_db()
        assert event.status == "failed"
        staff, headers, _ = staff_browser()
        assert (
            post(staff, f"/api/crm/notifications/{event.pk}/retry", {}, headers).status_code == 200
        )
        deliver_notification(event.pk, client)
        deliver_notification(event.pk, client)
    event.refresh_from_db()
    assert event.status == "sent" and event.attempts == 2 and len(attempts) == 2
    assert Notification.objects.filter(pk=event.pk).count() == 1
