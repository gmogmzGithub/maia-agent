import hashlib
import hmac
import json
import os
import uuid
from datetime import time, timedelta
from types import SimpleNamespace

import httpx
import pytest
from django.db import connection
from django.utils import timezone

from datalayer.appointments import date_time
from datalayer.followups import (
    DAYS,
    due_date,
    ensure_cycle,
    maintain,
    set_permission,
    template_options,
)
from datalayer.models import (
    Conversation,
    FollowupAttempt,
    FollowupCycle,
    FollowupPolicy,
    Message,
    Prospect,
    WhatsAppDelivery,
    WhatsAppEvent,
    WhatsAppTemplate,
)
from datalayer.whatsapp import process_event, store_events
from harness.followups import select_template
from harness.memory.context import build_messages
from tests.test_increment import browser, post
from tests.test_prospects import staff_browser
from worker.followups import process
from worker.whatsapp import deliver, sync_templates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup(settings, monkeypatch):
    now = date_time("2026-11-06T11:15:00-06:00")
    monkeypatch.setattr(timezone, "now", lambda: now)
    settings.WHATSAPP_ACCESS_TOKEN = "test-token"
    settings.WHATSAPP_PHONE_NUMBER_ID = "pilot-number"
    settings.WHATSAPP_BUSINESS_ACCOUNT_ID = "test-account"
    settings.WHATSAPP_API_VERSION = "v25.0"
    settings.META_APP_SECRET = "test-app-secret"
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "test-verification-token"
    prospect = Prospect.objects.create(
        phone="+523312345678",
        criteria={"operation": "rent", "kind": "house", "municipality": "Zapopan"},
    )
    conv = Conversation.objects.create(
        browser_id=uuid.uuid4(),
        prospect=prospect,
        declared_phone=prospect.phone,
        criteria=prospect.criteria,
        intent_started_at=now - timedelta(days=5),
        followup_permission=True,
    )
    message = Message.objects.create(
        conversation=conv, role="user", text="Quiero rentar una casa en Zapopan."
    )
    Message.objects.filter(pk=message.pk).update(created_at=now - timedelta(days=5))
    cycle = ensure_cycle(conv)
    template = WhatsAppTemplate.objects.create(
        name="retomar_busqueda",
        language="es_MX",
        body="¿Retomamos tu búsqueda de {{1}} para {{2}} en {{3}}?",
        status="APPROVED",
        fields=["kind", "operation", "municipality"],
        enabled=True,
        synced_at=now,
    )
    return conv, cycle, template, now


class Model:
    def __init__(self, template, callback=None, *, check_history=True):
        self.calls = 0
        self.template = template
        self.callback = callback
        self.check_history = check_history
        self.messages = self

    def create(self, **kwargs):
        assert not connection.in_atomic_block
        assert "Comunicación con el cliente" in kwargs["system"]
        assert "Comunicación humana" in kwargs["system"]
        if self.check_history:
            assert "Quiero rentar una casa en Zapopan" in kwargs["messages"][0]["content"]
        self.calls += 1
        if self.callback:
            self.callback()
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
            stop_reason="tool_use",
            content=[
                SimpleNamespace(
                    type="tool_use", name="select_followup", input={"template_id": self.template.pk}
                )
            ],
        )


def transport(callback=None):
    def send(request):
        assert not connection.in_atomic_block
        data = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-token"
        assert data["to"] == "523312345678"
        assert data["biz_opaque_callback_data"]
        if callback:
            return callback(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.outgoing"}]})

    return httpx.Client(transport=httpx.MockTransport(send))


def attempt(cycle, day=5):
    due = due_date(cycle, day)
    return FollowupAttempt.objects.create(
        cycle=cycle, day=day, due_at=due, expires_at=due + timedelta(hours=1)
    )


def payload(message=None, status=None, number="pilot-number", account="test-account"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": account,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": number},
                            "messages": [message] if message else [],
                            "statuses": [status] if status else [],
                        },
                    }
                ],
            }
        ],
    }


def incoming(now, text="Busco una casa", kind="text", id="wamid.incoming"):
    return {
        "id": id,
        "from": "523312345678",
        "timestamp": str(int(now.timestamp())),
        "type": kind,
        "text": {"body": text},
    }


def test_scheduler_deduplicates_and_records_missed_days(setup):
    conv, cycle, template, now = setup
    maintain()
    maintain()
    assert list(cycle.attempts.order_by("day").values_list("day", "status", "reason")) == [
        (1, "skipped", "expired"),
        (5, "queued", ""),
    ]
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM procrastinate_jobs WHERE task_name='process_followup'")
        assert c.fetchone()[0] == 1


@pytest.mark.parametrize("day", range(1, 30))
def test_exact_28_day_calendar(setup, monkeypatch, day):
    conv, cycle, template, now = setup
    cycle.started_at = now
    cycle.save()
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(days=day))
    maintain()
    assert set(cycle.attempts.values_list("day", flat=True)) == {d for d in DAYS if d <= day}
    cycle.refresh_from_db()
    assert bool(cycle.closed_at) == (day >= 29)


def test_one_draft_one_delivery_and_grounded_parameters(setup):
    conv, cycle, t, now = setup
    a = attempt(cycle)
    model = Model(t)
    client = transport()
    process(a.pk, model=model, transport=client)
    process(a.pk, model=model, transport=client)
    a.refresh_from_db()
    assert a.status == "sent" and model.calls == 1
    assert a.delivery.message.text == "¿Retomamos tu búsqueda de casa para rentar en Zapopan?"
    assert a.delivery.provider_id == "wamid.outgoing"
    assert a.execution.purpose == "followup"


def test_changed_schedule_discards_pending_attempt(setup):
    conv, cycle, template, now = setup
    pending = attempt(cycle)
    FollowupPolicy.objects.filter(pk=1).update(send_time=time(12))
    model = Model(template)
    process(pending.pk, model=model, transport=transport())
    pending.refresh_from_db()
    assert pending.status == "skipped"
    assert pending.reason == "schedule_changed"
    assert model.calls == 0
    assert not WhatsAppDelivery.objects.exists()


@pytest.mark.parametrize(
    "change,reason",
    [
        ("pause", "paused"),
        ("message", "recent_activity"),
        ("criteria", "context_changed"),
        ("optout", "closed"),
    ],
)
def test_change_during_generation_discards_draft(setup, change, reason):
    conv, cycle, t, now = setup

    def update():
        if change == "pause":
            Prospect.objects.filter(pk=conv.prospect_id).update(automation_paused=True)
        elif change == "message":
            Message.objects.create(conversation=conv, role="user", text="Hola otra vez")
        elif change == "criteria":
            Prospect.objects.filter(pk=conv.prospect_id).update(criteria={"operation": "sale"})
        else:
            set_permission(conv, False)

    a = attempt(cycle)
    process(a.pk, model=Model(t, update), transport=transport())
    a.refresh_from_db()
    assert a.status == "skipped" and a.reason == reason
    assert not WhatsAppDelivery.objects.exists()


def test_invalid_generation_is_reviewed_not_redrafted(setup):
    conv, cycle, t, now = setup
    bad = SimpleNamespace(pk=9999)
    model = Model(bad)
    a = attempt(cycle)
    process(a.pk, model=model)
    process(a.pk, model=model)
    a.refresh_from_db()
    assert a.status == "review" and model.calls == 1 and not WhatsAppDelivery.objects.exists()


@pytest.mark.parametrize("mode", ["timeout", "server_error", "invalid_response"])
def test_unknown_send_never_repeats_or_regenerates(setup, mode):
    conv, cycle, t, now = setup

    def send(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("lost response")
        if mode == "server_error":
            return httpx.Response(503)
        return httpx.Response(200, json={})

    a = attempt(cycle)
    model = Model(t)
    process(a.pk, model=model, transport=transport(send))
    process(a.pk, model=model, transport=transport(send))
    a.refresh_from_db()
    assert a.status == "uncertain" and model.calls == 1


def test_proposal_requires_approved_grounded_template(setup):
    conv, cycle, t, now = setup
    assert len(template_options(cycle)) == 1
    t.status = "PAUSED"
    t.save()
    assert not template_options(cycle)
    t.status = "APPROVED"
    t.fields = ["kind", "operation", "neighborhood"]
    t.save()
    assert not template_options(cycle)


def test_one_hour_window_no_late_delivery(setup, monkeypatch):
    conv, cycle, t, now = setup
    a = attempt(cycle)
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(hours=1))
    process(a.pk, model=Model(t), transport=transport())
    a.refresh_from_db()
    assert a.status == "skipped" and a.reason == "expired"


def test_signed_webhook_only_correct_account_and_deduplicated(setup, settings):
    conv, cycle, t, now = setup
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    raw = json.dumps(payload(incoming(now))).encode()
    assert (
        client.post("/api/whatsapp/webhook", data=raw, content_type="application/json").status_code
        == 403
    )
    signature = (
        "sha256=" + hmac.new(settings.META_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    )
    for _ in range(2):
        assert (
            client.post(
                "/api/whatsapp/webhook",
                data=raw,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=signature,
            ).status_code
            == 200
        )
    assert WhatsAppEvent.objects.count() == 1
    store_events(payload(incoming(now, id="other"), number="different-number"))
    assert WhatsAppEvent.objects.count() == 1
    assert (
        client.get(
            "/api/whatsapp/webhook",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verification-token",
                "hub.challenge": "123",
            },
        ).content
        == b"123"
    )


def test_incoming_identity_is_separate_from_browser(setup):
    conv, cycle, t, now = setup
    store_events(payload(incoming(now)))
    event = WhatsAppEvent.objects.get()
    process_event(event.pk)
    process_event(event.pk)
    event.refresh_from_db()
    assert event.status == "processed"
    wa = Conversation.objects.get(channel="whatsapp")
    assert wa.prospect_id == conv.prospect_id and wa.browser_id is None
    assert wa.messages.count() == 1 and wa.context_origin_id is None
    assert conv.messages.count() == 1


def test_mexican_legacy_sender_matches_canonical_prospect(setup):
    conv, cycle, template, now = setup
    data = incoming(now)
    data["from"] = "5213312345678"
    store_events(payload(data))
    event = WhatsAppEvent.objects.get()
    process_event(event.pk)
    event.refresh_from_db()
    assert event.status == "processed"
    wa = Conversation.objects.get(channel="whatsapp")
    assert wa.prospect_id == conv.prospect_id
    assert wa.declared_phone == "+523312345678"
    assert wa.whatsapp_sender == "5213312345678"
    assert wa.messages.filter(role="user").count() == 1
    assert Prospect.objects.count() == 1


def test_mexican_reply_uses_canonical_recipient_and_accepts_legacy_receipt(setup):
    conv, cycle, template, now = setup
    data = incoming(now, kind="audio")
    data["from"] = "5213312345678"
    store_events(payload(data))
    process_event(WhatsAppEvent.objects.get().pk)
    delivery = WhatsAppDelivery.objects.get()
    assert delivery.recipient == "5213312345678"
    deliver(delivery.pk, client=transport())
    delivery.refresh_from_db()
    assert delivery.status == "sent"
    store_events(
        payload(
            status={
                "id": delivery.provider_id,
                "status": "delivered",
                "timestamp": str(int(now.timestamp())),
                "recipient_id": "523312345678",
            }
        )
    )
    process_event(WhatsAppEvent.objects.get(payload__kind="statuses").pk)
    delivery.refresh_from_db()
    assert delivery.status == "delivered"


@pytest.mark.parametrize(
    "text", ["No quiero recibir más mensajes", "No quiero recibir mas mensajes"]
)
def test_explicit_optout_closes_cycle_and_new_search_does_not_reopen_it(setup, text):
    from datalayer.tool_actions import apply_tool

    conv, cycle, template, now = setup
    store_events(payload(incoming(now, text=text)))
    process_event(WhatsAppEvent.objects.get().pk)
    wa = Conversation.objects.get(channel="whatsapp")
    conv.prospect.refresh_from_db()
    cycle.refresh_from_db()
    assert conv.prospect.contact_opted_out
    assert wa.followup_permission is False
    assert cycle.closed_at and cycle.reason == "opted_out" and not cycle.permission
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM procrastinate_jobs WHERE task_name='attend_conversation'"
        )
        assert cursor.fetchone()[0] == 0

    store_events(
        payload(
            incoming(
                now,
                text="Sigo buscando un departamento en renta en Zapopan",
                id="wamid.resume-search",
            )
        )
    )
    process_event(WhatsAppEvent.objects.get(key="in:wamid.resume-search").pk)
    wa.refresh_from_db()
    apply_tool(
        wa.pk,
        wa.revision,
        "search_properties",
        {"criteria_patch": {"operation": "rent", "municipality": "Zapopan"}},
    )
    conv.prospect.refresh_from_db()
    assert conv.prospect.contact_opted_out
    assert FollowupCycle.objects.filter(prospect=conv.prospect).count() == 1
    assert not FollowupCycle.objects.filter(prospect=conv.prospect, closed_at__isnull=True).exists()


def test_audio_fallback_and_optout_do_not_call_llm(setup):
    conv, cycle, t, now = setup
    store_events(payload(incoming(now, kind="audio")))
    process_event(WhatsAppEvent.objects.get().pk)
    wa = Conversation.objects.get(channel="whatsapp")
    assert "escribir" in wa.messages.last().text
    store_events(payload(incoming(now, text="No quiero recibir mensajes", id="wamid.stop")))
    process_event(WhatsAppEvent.objects.get(key="in:wamid.stop").pk)
    cycle.refresh_from_db()
    conv.prospect.refresh_from_db()
    assert cycle.closed_at and conv.prospect.contact_opted_out


def test_delivery_status_reconciles_unknown_without_downgrade(setup):
    conv, cycle, t, now = setup
    delivery = WhatsAppDelivery.objects.create(
        conversation=conv, recipient="523312345678", event_key="x", status="uncertain"
    )
    for state in ["read", "sent", "failed", "delivered"]:
        store_events(
            payload(
                status={
                    "id": "wamid.status",
                    "status": state,
                    "timestamp": str(int(now.timestamp())),
                    "recipient_id": delivery.recipient,
                    "biz_opaque_callback_data": str(delivery.pk),
                }
            )
        )
        process_event(WhatsAppEvent.objects.order_by("pk").last().pk)
    delivery.refresh_from_db()
    assert delivery.status == "read" and delivery.provider_id == "wamid.status"


def test_crm_auth_and_no_retry_unknown_delivery(setup):
    conv, cycle, t, now = setup
    owner, headers = browser()
    assert owner.get("/api/crm/followup-policy").status_code == 401
    staff, headers, user = staff_browser()
    delivery = WhatsAppDelivery.objects.create(
        conversation=conv, recipient="523312345678", event_key="x", status="uncertain"
    )
    assert (
        post(staff, f"/api/crm/whatsapp/deliveries/{delivery.pk}/retry", {}, headers).status_code
        == 409
    )


def test_window_uses_whatsapp_timestamp_not_processing_time(setup):
    conv, cycle, t, now = setup
    store_events(payload(incoming(now - timedelta(days=2), kind="audio")))
    process_event(WhatsAppEvent.objects.get().pk)
    delivery = WhatsAppDelivery.objects.get()
    deliver(delivery.pk, client=transport())
    delivery.refresh_from_db()
    assert delivery.status == "skipped" and delivery.error_code == "outside_service_window"


def test_pending_incoming_cancels_followup_before_processing(setup):
    conv, cycle, t, now = setup
    store_events(payload(incoming(now)))
    a = attempt(cycle)
    model = Model(t)
    process(a.pk, model=model)
    a.refresh_from_db()
    assert a.status == "skipped" and a.reason == "incoming_pending" and model.calls == 0


def test_failed_delivery_is_not_presented_as_a_sent_message(setup):
    from datalayer.conversations import conversation_output
    from datalayer.crm import crm_conversation

    conv, cycle, t, now = setup
    a = attempt(cycle)
    process(a.pk, model=Model(t), transport=transport(lambda req: httpx.Response(400)))
    assert len(conversation_output(conv)["messages"]) == 1
    assert crm_conversation(conv)["messages"][-1]["delivery_status"] == "failed"


def test_template_change_before_retry_blocks_send(setup):
    conv, cycle, t, now = setup
    a = attempt(cycle)
    process(a.pk, model=Model(t), transport=transport(lambda req: httpx.Response(400)))
    a.refresh_from_db()
    delivery = a.delivery
    delivery.status = "queued"
    delivery.save()
    t.status = "PAUSED"
    t.save()
    deliver(delivery.pk, client=transport())
    delivery.refresh_from_db()
    assert delivery.status == "skipped" and delivery.error_code == "template_changed"


def test_completed_cycle_never_restarts_automatically(setup, monkeypatch):
    conv, cycle, t, now = setup
    cycle.closed_at = now
    cycle.save()
    Message.objects.create(conversation=conv, role="user", text="Ahora busco comprar")
    assert ensure_cycle(conv).pk == cycle.pk
    assert FollowupCycle.objects.count() == 1
    monkeypatch.setattr(timezone, "now", lambda: now + timedelta(days=1))
    Message.objects.create(conversation=conv, role="user", text="Quiero retomar mi búsqueda")
    next_cycle = ensure_cycle(conv, new=True)
    assert next_cycle.pk != cycle.pk and FollowupCycle.objects.count() == 2


def test_sync_only_approves_catalog_from_meta_and_keeps_local_mapping(setup):
    conv, cycle, t, now = setup

    def read(request):
        assert not connection.in_atomic_block and request.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": t.name,
                        "language": t.language,
                        "status": "PAUSED",
                        "components": [{"type": "BODY", "text": t.body}],
                    }
                ]
            },
        )

    assert sync_templates(client=httpx.Client(transport=httpx.MockTransport(read))) == 1
    t.refresh_from_db()
    assert t.status == "PAUSED" and t.fields == ["kind", "operation", "municipality"]


def test_website_permission_is_explicit_and_owned_by_browser(setup):
    conv, cycle, t, now = setup
    client, headers = browser()
    conv.browser_id = client.session["browser_id"]
    conv.save()
    foreign, foreign_headers = browser()
    url = f"/api/conversations/{conv.pk}/followup-permission"
    response = foreign.put(
        url,
        data=json.dumps({"allowed": False}),
        content_type="application/json",
        **foreign_headers,
    )
    assert response.status_code == 404
    response = client.put(
        url,
        data=json.dumps({"allowed": False}),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    cycle.refresh_from_db()
    assert cycle.closed_at and cycle.reason == "opted_out"


def test_authenticated_reply_resumes_only_its_followup_context(setup):
    from datalayer.turns import load_turn

    conv, cycle, t, now = setup
    a = attempt(cycle)
    process(a.pk, model=Model(t), transport=transport())
    store_events(payload(incoming(now, text="Sí, retomemos esa búsqueda")))
    process_event(WhatsAppEvent.objects.get().pk)
    wa = Conversation.objects.get(channel="whatsapp")
    assert wa.context_origin_id == conv.pk
    turn = load_turn(wa.pk)
    assert "Quiero rentar una casa en Zapopan" in json.dumps(build_messages(turn))


def test_scheduler_requeues_a_durable_pending_attempt(setup):
    conv, cycle, t, now = setup
    a = attempt(cycle)
    maintain()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs WHERE task_name='process_followup'")
        assert cursor.fetchone()[0] == 1
    a.refresh_from_db()
    assert a.status == "queued"


@pytest.mark.skipif(
    os.getenv("MAIA_LIVE_HAIKU_CHECK") != "1",
    reason="Requiere invocación explícita; usa la API real de Haiku.",
)
def test_real_haiku_selects_a_grounded_template_without_sending(setup, settings):
    from datalayer.followups import context
    from datalayer.models import Execution

    conv, cycle, t, now = setup
    execution = Execution.objects.create(
        conversation=conv, revision=0, purpose="followup", model=settings.ANTHROPIC_MODEL
    )
    selected = select_template(context(cycle), template_options(cycle), execution)
    assert selected["id"] == t.pk
    assert not WhatsAppDelivery.objects.exists()
    execution.refresh_from_db()
    assert execution.status == "completed" and execution.input_tokens > 0


@pytest.fixture
def pilot(setup):
    from datalayer.followup_pilot import start_pilot
    from datalayer.followups import PILOT_TEMPLATES

    conv, old, template, now = setup
    old.closed_at, old.reason, old.permission = now, "opted_out", False
    old.save()
    conv.channel, conv.whatsapp_sender = "whatsapp", "523312345678"
    conv.save()
    prospect = conv.prospect
    prospect.contact_opted_out = True
    prospect.save()
    bodies = (
        ("Sobre tu búsqueda para {{1}}, ¿quieres revisar opciones?", ["operation"]),
        ("¿Seguimos buscando en {{1}}?", ["municipality"]),
        ("Retomo tu búsqueda de {{1}} en {{2}}. ¿Revisamos opciones?", ["kind", "municipality"]),
    )
    templates = []
    for name, (body, fields) in zip(PILOT_TEMPLATES, bodies):
        templates.append(
            WhatsAppTemplate.objects.create(
                name=name,
                language="es_MX",
                body=body,
                fields=fields,
                status="APPROVED",
                enabled=False,
                synced_at=now,
            )
        )
    cycle, created = start_pilot(prospect.phone)
    assert created
    return conv, cycle, templates, now


def test_pilot_is_scoped_idempotent_and_has_eight_bounded_attempts(pilot):
    from datalayer.followup_pilot import start_pilot
    from datalayer.followups import end_date, send_window

    conv, cycle, templates, now = pilot
    repeat, created = start_pilot(conv.prospect.phone)
    assert not created and repeat.pk == cycle.pk
    assert [due_date(cycle, d) - now for d in DAYS] == [
        timedelta(minutes=5 + index * 30) for index in range(8)
    ]
    assert send_window(cycle) == timedelta(minutes=10)
    assert end_date(cycle) == now + timedelta(minutes=225)
    normal = FollowupCycle(started_at=now)
    assert due_date(normal, 5).date() == (now + timedelta(days=5)).date()
    assert send_window(normal) == timedelta(hours=1)
    assert not any(t.enabled for t in templates)
    conv.prospect.refresh_from_db()
    assert not conv.prospect.contact_opted_out


def test_pilot_first_three_cover_each_template_without_enabling_globally(pilot):
    conv, cycle, templates, now = pilot
    for day, template in zip(DAYS[:3], templates):
        assert [o["id"] for o in template_options(cycle, day)] == [template.pk]
    assert len(template_options(cycle, DAYS[3])) == 3
    normal = FollowupCycle(prospect=conv.prospect)
    assert all(o["id"] not in {t.pk for t in templates} for o in template_options(normal))


def test_pilot_actual_worker_sends_each_first_template_once(pilot, monkeypatch):
    conv, cycle, templates, now = pilot
    sent = []

    def capture(request):
        sent.append(json.loads(request.content)["template"]["name"])
        return httpx.Response(200, json={"messages": [{"id": f"wamid.pilot.{len(sent)}"}]})

    for day, template in zip(DAYS[:3], templates):
        monkeypatch.setattr(timezone, "now", lambda day=day: due_date(cycle, day))
        maintain()
        a = cycle.attempts.get(day=day)
        model = Model(template, check_history=False)
        process(a.pk, model=model, transport=transport(capture))
        process(a.pk, model=model, transport=transport(capture))
        a.refresh_from_db()
        assert a.status == "sent" and model.calls == 1
    assert sent == [t.name for t in templates]
    assert WhatsAppDelivery.objects.count() == 3


def test_pilot_recent_reply_pauses_for_five_minutes_and_optout_stops(pilot, monkeypatch):
    from datalayer.followups import eligible

    conv, cycle, templates, now = pilot
    Message.objects.create(conversation=conv, role="user", text="Sigamos buscando")
    cycle.prospect.refresh_from_db()
    assert eligible(cycle, now + timedelta(minutes=4)) == "recent_activity"
    assert eligible(cycle, now + timedelta(minutes=6)) == ""
    set_permission(conv, False)
    cycle.refresh_from_db()
    assert cycle.closed_at and not cycle.permission
    process(attempt(cycle).pk, model=Model(templates[0]), transport=transport())
    assert not WhatsAppDelivery.objects.exists()


def test_pilot_completion_restores_optout_and_does_not_restart(pilot, monkeypatch):
    from datalayer.followups import end_date

    conv, cycle, templates, now = pilot
    monkeypatch.setattr(timezone, "now", lambda: end_date(cycle))
    maintain()
    maintain()
    cycle.refresh_from_db()
    conv.refresh_from_db()
    conv.prospect.refresh_from_db()
    assert cycle.closed_at and not cycle.permission
    assert conv.prospect.contact_opted_out and conv.followup_permission is False
    assert cycle.attempts.count() == 8
    assert not WhatsAppDelivery.objects.exists()
    assert ensure_cycle(conv).pk == cycle.pk


def test_pilot_recipient_change_fails_closed(pilot):
    from datalayer.followups import eligible

    conv, cycle, templates, now = pilot
    cycle.prospect.phone = "+523387654321"
    assert eligible(cycle, now) == "pilot_recipient_changed"


def test_pilot_preserves_past_visit_and_suspends_on_current_visit(pilot):
    from datalayer.followups import eligible
    from datalayer.models import Advisor, Appointment, CalendarConnection, Property

    conv, cycle, templates, now = pilot
    advisor = Advisor.objects.create(name="PRUEBA piloto")
    prop = Property.objects.create(
        title="PRUEBA piloto",
        kind="house",
        operation="rent",
        price=100,
        municipality="Zapopan",
        neighborhood="Centro",
        advisor=advisor,
    )
    calendar = CalendarConnection.objects.create(
        advisor=advisor,
        subject="pilot",
        email="pilot@example.test",
        credentials="unused",
    )
    visit = Appointment.objects.create(
        conversation=conv,
        prospect=cycle.prospect,
        property=prop,
        advisor=advisor,
        connection=calendar,
        connection_generation=calendar.generation,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2, hours=-1),
        status="confirmed",
    )
    cycle.prospect.status = "scheduled"
    assert eligible(cycle, now) == ""
    visit.refresh_from_db()
    assert visit.status == "confirmed"
    visit.start, visit.end = now + timedelta(days=1), now + timedelta(days=1, hours=1)
    visit.save()
    assert eligible(cycle, now) == "appointment"
    cycle.refresh_from_db()
    assert cycle.suspended


def test_pilot_unapproved_template_during_generation_never_sends(pilot, monkeypatch):
    conv, cycle, templates, now = pilot
    monkeypatch.setattr(timezone, "now", lambda: due_date(cycle, 1))
    maintain()
    a = cycle.attempts.get(day=1)

    def withdraw():
        WhatsAppTemplate.objects.filter(pk=templates[0].pk).update(status="REJECTED")

    process(a.pk, model=Model(templates[0], withdraw, check_history=False), transport=transport())
    a.refresh_from_db()
    assert a.status == "review" and a.reason == "template_changed"
    assert not WhatsAppDelivery.objects.exists()


def test_pilot_expired_new_intention_cannot_inherit_temporary_permission(pilot, monkeypatch):
    from datalayer.followups import end_date

    conv, cycle, templates, now = pilot
    monkeypatch.setattr(timezone, "now", lambda: end_date(cycle) + timedelta(minutes=1))
    Message.objects.create(conversation=conv, role="user", text="Otra búsqueda")
    replacement = ensure_cycle(conv, new=True)
    conv.prospect.refresh_from_db()
    assert not replacement.pilot and not replacement.permission
    assert conv.prospect.contact_opted_out


def test_pilot_not_interested_closes_and_restores_previous_optout(pilot):
    from datalayer.followups import eligible

    conv, cycle, templates, now = pilot
    cycle.prospect.status = "not_interested"
    assert eligible(cycle, now) == "not_interested"
    cycle.refresh_from_db()
    cycle.prospect.refresh_from_db()
    assert cycle.closed_at and not cycle.permission and cycle.prospect.contact_opted_out


def test_pilot_context_keeps_new_intention_separate_from_old_visit_request(pilot):
    from datalayer.followups import context

    conv, cycle, templates, now = pilot
    old = Message.objects.create(conversation=conv, role="user", text="Busquemos horarios")
    Message.objects.filter(pk=old.pk).update(created_at=now - timedelta(minutes=1))
    current = Message.objects.create(conversation=conv, role="user", text="Ahora prefiero otra zona")
    data = context(cycle)
    assert data["history"] == [{"role": "user", "text": current.text}]
    assert data["criteria"]["operation"] == "rent"
    assert Message.objects.filter(pk=old.pk, text="Busquemos horarios").exists()
