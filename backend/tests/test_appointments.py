import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from asgiref.sync import sync_to_async
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from datalayer.appointments import booking_policy, submit, validate_slot, validate_windows
from datalayer.booking_tools import visit_tool
from datalayer.conversations import conversation_output
from datalayer.models import (
    Advisor,
    Appointment,
    CalendarAuthorization,
    CalendarConnection,
    Conversation,
    Notification,
    Property,
    Prospect,
)
from tests.test_increment import ScriptedClient, browser, post, response
from tests.test_prospects import staff_browser
from worker.appointments import inspect_appointment, process
from worker.google_calendar import CalendarError, GoogleCalendar, decrypt, encrypt

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def isolate_jobs():
    assert connection.settings_dict["NAME"].startswith("test_")
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE procrastinate_jobs RESTART IDENTITY CASCADE")


@pytest.fixture
def setup(settings):
    settings.CALENDAR_ENCRYPTION_KEY = Fernet.generate_key().decode()
    advisor = Advisor.objects.create(name="PRUEBA · Visitas", is_default=True)
    owner = Advisor.objects.create(name="PRUEBA · Responsable comercial")
    prop = Property.objects.create(
        title="PRUEBA · Casa",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=32000,
        published=True,
        advisor=advisor,
    )
    conn = CalendarConnection.objects.create(
        advisor=advisor,
        subject="test-google-subject",
        email="advisor@example.test",
        credentials=encrypt(
            {
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "expires_at": timezone.now().timestamp() + 3600,
            }
        ),
    )
    prospect = Prospect.objects.create(phone="+523312345678", advisor=owner)
    conversation = Conversation.objects.create(
        browser_id=uuid.uuid4(), prospect=prospect, declared_phone=prospect.phone
    )
    start = (timezone.localtime() + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    while start.weekday() >= 5:
        start += timedelta(days=1)
    return conversation, prop, conn, start


class Calendar:
    def __init__(self):
        self.events, self.inserts, self.updates, self.deletes, self.occupied = {}, 0, 0, 0, []
        self.lose_response = False

    def busy(self, start, end):
        assert not connection.in_atomic_block
        return self.occupied

    def event(self, key):
        assert not connection.in_atomic_block
        if key not in self.events:
            raise CalendarError("google_http_404", 404)
        return self.events[key]

    def create(self, body):
        assert not connection.in_atomic_block
        self.inserts += 1
        event = {**body, "etag": "version-1", "status": "confirmed"}
        self.events[body["id"]] = event
        if self.lose_response:
            raise CalendarError("google_response_unknown")
        return event

    def change(self, key, body, etag):
        assert not connection.in_atomic_block
        if self.events[key]["etag"] != etag:
            raise CalendarError("google_http_412", 412)
        self.updates += 1
        self.events[key] = {**self.events[key], **body, "etag": "version-2"}
        return self.events[key]

    def delete(self, key, etag):
        assert not connection.in_atomic_block
        self.deletes += 1
        self.events[key] = {**self.events[key], "status": "cancelled", "etag": "deleted"}


def reserve(setup, calendar=None):
    conversation, prop, conn, start = setup
    a = submit(conversation, prop, start, request_id=uuid.uuid4())
    calendar = calendar or Calendar()
    process(a.operations.get().pk, calendar)
    a.refresh_from_db()
    return a, calendar


def test_create_idempotency_responsibilities_and_no_network_transaction(setup):
    conversation, prop, conn, start = setup
    key = uuid.uuid4()
    a = submit(conversation, prop, start, request_id=key)
    assert submit(conversation, prop, start, request_id=key).pk == a.pk
    assert a.status == "pending" and a.advisor_id == prop.advisor_id
    calendar = Calendar()
    process(a.operations.get().pk, calendar)
    process(a.operations.get().pk, calendar)
    a.refresh_from_db()
    conversation.prospect.refresh_from_db()
    assert a.status == "confirmed" and calendar.inserts == 1
    assert conversation.prospect.status == "scheduled"
    assert set(Notification.objects.values_list("advisor_id", flat=True)) == {
        prop.advisor_id,
        conversation.prospect.advisor_id,
    }


def test_lost_create_response_queries_same_event_without_second_insert(setup):
    calendar = Calendar()
    calendar.lose_response = True
    a, calendar = reserve(setup, calendar)
    op = a.operations.get()
    assert op.status == "verifying" and a.status == "pending"
    op.verify_after = timezone.now() - timedelta(seconds=1)
    op.save()
    process(op.pk, calendar)
    a.refresh_from_db()
    op.refresh_from_db()
    assert a.status == "confirmed" and op.status == "completed" and calendar.inserts == 1


def test_unknown_outcome_retains_hold_and_requires_human_after_five_checks(setup):
    a = submit(setup[0], setup[1], setup[3], request_id=uuid.uuid4())
    op = a.operations.get()
    op.sent_at = timezone.now()
    op.status = "verifying"
    op.attempts = 5
    op.verify_after = timezone.now() - timedelta(seconds=1)
    op.save()
    calendar = Calendar()
    process(op.pk, calendar)
    op.refresh_from_db()
    a.refresh_from_db()
    assert op.status == "review" and a.status == "review" and calendar.inserts == 0
    with pytest.raises(ValidationError):
        submit(setup[0], setup[1], setup[3], request_id=uuid.uuid4())


def test_verification_permission_error_does_not_prove_creation_failed(setup):
    calendar = Calendar()
    calendar.lose_response = True
    a, calendar = reserve(setup, calendar)
    op = a.operations.get()
    op.verify_after = timezone.now() - timedelta(seconds=1)
    op.save()

    class Forbidden(Calendar):
        def event(self, key):
            raise CalendarError("google_http_403", 403)

    process(op.pk, Forbidden())
    op.refresh_from_db()
    a.refresh_from_db()
    assert op.status == "verifying" and a.status == "pending"
    with pytest.raises(ValidationError):
        submit(setup[0], setup[1], setup[3], request_id=uuid.uuid4())


def test_lost_cancel_response_recovers_gone_event_without_second_delete(setup):
    a, calendar = reserve(setup)

    class LostCancellation(Calendar):
        def delete(self, key, etag):
            self.deletes += 1
            self.events.pop(key)
            raise CalendarError("google_response_unknown")

        def event(self, key):
            if key not in self.events:
                raise CalendarError("google_http_410", 410)
            return self.events[key]

    recovery = LostCancellation()
    recovery.events = calendar.events
    submit(
        a.conversation, a.property, a.start, request_id=uuid.uuid4(), action="cancel", appointment=a
    )
    op = a.operations.order_by("created_at").last()
    process(op.pk, recovery)
    op.refresh_from_db()
    assert op.status == "verifying"
    op.verify_after = timezone.now() - timedelta(seconds=1)
    op.save()
    process(op.pk, recovery)
    a.refresh_from_db()
    assert a.status == "cancelled" and recovery.deletes == 1


def test_concurrent_reservations_only_one_holds_resources(setup):
    c, p, conn, start = setup
    booking_policy()

    def attempt(_):
        close_old_connections()
        try:
            submit(
                Conversation.objects.get(pk=c.pk),
                Property.objects.get(pk=p.pk),
                start,
                request_id=uuid.uuid4(),
            )
            return "reserved"
        except ValidationError:
            return "unavailable"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["reserved", "unavailable"]
    assert Appointment.objects.count() == 1


@pytest.mark.parametrize("change", ["property", "advisor", "prospect"])
def test_resource_overlap_is_rejected(setup, change):
    c, p, conn, start = setup
    submit(c, p, start, request_id=uuid.uuid4())
    if change == "property":
        other = Prospect.objects.create(phone="+523312345679")
        c = Conversation.objects.create(
            browser_id=uuid.uuid4(), prospect=other, declared_phone=other.phone
        )
    elif change == "advisor":
        p.pk = None
        p.reference = "TEST-OTHER"
        p.save()
        other = Prospect.objects.create(phone="+523312345679")
        c = Conversation.objects.create(
            browser_id=uuid.uuid4(), prospect=other, declared_phone=other.phone
        )
    else:
        advisor = Advisor.objects.create(name="PRUEBA · Otro")
        CalendarConnection.objects.create(
            advisor=advisor,
            subject="other",
            email="other@example.test",
            credentials=conn.credentials,
        )
        p.pk = None
        p.reference = "TEST-OTHER"
        p.advisor = advisor
        p.save()
    with pytest.raises(ValidationError):
        submit(c, p, start + timedelta(minutes=30), request_id=uuid.uuid4())


def test_move_preserves_original_until_google_confirms_and_cancel_updates_stage(setup):
    a, calendar = reserve(setup)
    original = a.start
    submit(
        a.conversation,
        a.property,
        original + timedelta(hours=1),
        request_id=uuid.uuid4(),
        action="move",
        appointment=a,
    )
    a.refresh_from_db()
    assert a.start == original
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    assert a.start == original + timedelta(hours=1) and calendar.updates == 1
    submit(
        a.conversation, a.property, a.start, request_id=uuid.uuid4(), action="cancel", appointment=a
    )
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    a.prospect.refresh_from_db()
    assert a.status == "cancelled" and a.prospect.status == "attending" and calendar.deletes == 1


def test_external_edit_is_not_overwritten_and_can_be_accepted(setup):
    a, calendar = reserve(setup)
    calendar.events[a.google_id]["etag"] = "external"
    calendar.events[a.google_id]["start"]["dateTime"] = (a.start + timedelta(hours=1)).isoformat()
    calendar.events[a.google_id]["end"]["dateTime"] = (a.end + timedelta(hours=1)).isoformat()
    inspect_appointment(a.pk, calendar)
    a.refresh_from_db()
    assert a.status == "review" and calendar.updates == 0
    _, _, staff = staff_browser()
    submit(
        a.conversation,
        a.property,
        a.start,
        request_id=uuid.uuid4(),
        action="accept",
        appointment=a,
        actor=staff,
    )
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    assert a.status == "confirmed" and a.etag == "external"


def test_google_rejection_does_not_confirm_and_disconnect_keeps_record(setup):
    c, p, conn, start = setup
    a = submit(c, p, start, request_id=uuid.uuid4())
    conn.connected = False
    conn.save()
    process(a.operations.get().pk, Calendar())
    a.refresh_from_db()
    assert a.status == "review" and a.operations.get().error_code == "calendar_disconnected"


def test_slot_rules_and_window_validation(setup):
    c, p, conn, start = setup
    policy = booking_policy()
    for invalid in (
        timezone.localtime() + timedelta(minutes=20),
        start + timedelta(minutes=15),
        start.replace(hour=13, minute=30),
        start + timedelta(days=30),
    ):
        with pytest.raises(ValidationError):
            validate_slot(p, invalid, invalid + timedelta(hours=1), policy)
    with pytest.raises(ValidationError):
        validate_windows(
            [
                {"day": 0, "start": "10:00", "end": "14:00"},
                {"day": 0, "start": "13:00", "end": "15:00"},
            ]
        )


def test_proposal_needs_button_and_original_browser(setup):
    c, p, conn, start = setup
    owner, headers = browser()
    c.browser_id = owner.session["browser_id"]
    c.save()
    result = visit_tool(
        c.pk,
        c.revision,
        "prepare_visit",
        {"action": "create", "property_id": p.pk, "start": start.isoformat()},
    )
    proposal_id = result["proposal"]["id"]
    assert not Appointment.objects.exists()

    other, other_headers = browser()
    path = f"/api/conversations/{c.pk}/visits/confirm"
    assert (
        post(
            other, path, {"proposal_id": proposal_id, "confirmed": True}, other_headers
        ).status_code
        == 404
    )
    first = post(owner, path, {"proposal_id": proposal_id, "confirmed": True}, headers)
    assert first.status_code == 200
    assert (
        post(owner, path, {"proposal_id": proposal_id, "confirmed": True}, headers).status_code
        == 200
    )
    assert Appointment.objects.count() == 1
    assert conversation_output(c)["visit_proposal"] is None
    assert other.get(f"/api/conversations/{c.pk}").status_code == 404


def test_new_conversation_with_same_phone_cannot_modify_old_appointment(setup):
    a, calendar = reserve(setup)
    c = Conversation.objects.create(
        browser_id=uuid.uuid4(), prospect=a.prospect, declared_phone=a.prospect.phone
    )
    with pytest.raises(ValidationError):
        submit(c, a.property, a.start, request_id=uuid.uuid4(), action="cancel", appointment=a)


def test_google_http_transport_encrypts_and_restricts_projection(setup):
    conn = setup[2]
    assert "secret-access" not in conn.credentials
    assert decrypt(conn.credentials)["refresh_token"] == "secret-refresh"
    paths = []

    def transport(request):
        assert not connection.in_atomic_block
        assert request.headers["Authorization"] == "Bearer secret-access"
        paths.append(str(request.url.path))
        return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        assert GoogleCalendar(conn, client).busy(setup[3], setup[3] + timedelta(hours=1)) == []
    assert paths == ["/calendar/v3/freeBusy"]


def test_oauth_state_binds_staff_session_and_tokens_wait_for_explicit_assignment(
    setup, settings, monkeypatch
):
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = "test-client", "test-secret"
    client, headers, actor = staff_browser()
    advisor = Advisor.objects.create(name="PRUEBA · Nuevo")
    result = post(client, f"/api/crm/advisors/{advisor.pk}/calendar/connect", {}, headers)
    state = parse_qs(urlparse(result.json()["url"]).query)["state"][0]
    monkeypatch.setattr(
        "api.calendar_auth.token_exchange",
        lambda data: {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "scope": "https://www.googleapis.com/auth/calendar.events.owned https://www.googleapis.com/auth/calendar.freebusy",
        },
    )
    monkeypatch.setattr(
        "api.calendar_auth.google_request",
        lambda *a, **kw: {"email": "owner@example.test", "sub": "new-sub", "email_verified": True},
    )
    other, _, _ = staff_browser()
    assert other.get("/api/calendar/callback", {"state": state, "code": "fake"}).status_code == 404
    assert client.get("/api/calendar/callback", {"state": state, "code": "fake"}).status_code == 302
    assert not CalendarConnection.objects.filter(advisor=advisor).exists()
    pending = client.get(f"/api/crm/advisors/{advisor.pk}/calendar").json()["pending"]
    result = post(
        client,
        f"/api/crm/advisors/{advisor.pk}/calendar/confirm",
        {"authorization_id": pending["id"]},
        headers,
    )
    assert result.status_code == 200 and result.json()["email"] == "owner@example.test"
    assert "test-access" not in result.content.decode()
    assert CalendarAuthorization.objects.get(pk=pending["id"]).consumed


def test_oauth_callback_cannot_be_replayed_after_account_is_prepared(setup, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = "test-client", "test-secret"
    client, headers, _ = staff_browser()
    path = f"/api/crm/advisors/{setup[1].advisor_id}/calendar/connect"
    state = parse_qs(urlparse(post(client, path, {}, headers).json()["url"]).query)["state"][0]
    calls = []

    def exchange(data):
        calls.append(True)
        return {
            "access_token": "test",
            "refresh_token": "test",
            "scope": "https://www.googleapis.com/auth/calendar.events.owned https://www.googleapis.com/auth/calendar.freebusy",
        }

    monkeypatch.setattr("api.calendar_auth.token_exchange", exchange)
    monkeypatch.setattr(
        "api.calendar_auth.google_request",
        lambda *a, **kw: {"email": "owner@example.test", "sub": "new-sub", "email_verified": True},
    )
    assert client.get("/api/calendar/callback", {"state": state, "code": "fake"}).status_code == 302
    assert client.get("/api/calendar/callback", {"state": state, "code": "fake"}).status_code == 404
    assert len(calls) == 1


def test_staff_booking_without_calendar_preserves_the_request(setup):
    c, p, conn, start = setup
    conn.connected = False
    conn.save()
    staff, headers, _ = staff_browser()
    response = post(
        staff,
        "/api/crm/appointments",
        {
            "conversation_id": str(c.pk),
            "property_id": p.pk,
            "start": start.isoformat(),
            "request_id": str(uuid.uuid4()),
            "confirmed": True,
        },
        headers,
    )
    assert response.status_code == 409
    c.refresh_from_db()
    assert c.human_requested and Notification.objects.filter(conversation=c).exists()
    assert not Appointment.objects.exists()


def test_authentication_and_csrf_protect_private_calendar_configuration(setup):
    anonymous, _ = browser()
    assert anonymous.get("/api/crm/appointments").status_code == 401
    assert anonymous.get(f"/api/crm/advisors/{setup[1].advisor_id}/calendar").status_code == 401
    staff, _, _ = staff_browser()
    assert (
        staff.post(
            "/api/crm/booking-policy", data="{}", content_type="application/json"
        ).status_code
        != 200
    )
    response = staff.put(
        "/api/crm/booking-policy",
        data=json.dumps({"notice_hours": 3, "horizon_days": 7}),
        content_type="application/json",
    )
    assert response.status_code == 403


def test_future_configuration_changes_do_not_reassign_existing_visit(setup):
    a, calendar = reserve(setup)
    original_advisor = a.advisor_id
    prop = a.property
    prop.visit_duration = 30
    prop.visit_windows = []
    prop.advisor = None
    prop.save()
    a.refresh_from_db()
    assert a.duration == 60 and a.advisor_id == original_advisor and a.status == "confirmed"


@pytest.mark.parametrize("quick_action", [False, True])
def test_unpublishing_notifies_without_cancelling(setup, quick_action):
    from datalayer.inventory import managed_property, save_property, set_publication
    from datalayer.schemas import PropertyInput

    a, calendar = reserve(setup)
    values = managed_property(a.property)
    values = {k: v for k, v in values.items() if k in PropertyInput.model_fields}
    values["published"] = False
    if quick_action:
        set_publication(a.property_id, False)
        set_publication(a.property_id, False)
    else:
        save_property(PropertyInput.model_validate(values), a.property)
    a.refresh_from_db()
    assert a.status == "confirmed" and calendar.deletes == 0
    assert Notification.objects.filter(summary__contains="despublicada").count() == 2


def test_external_acceptance_rejects_conflicting_reservation(setup):
    a, calendar = reserve(setup)
    other = submit(
        a.conversation, a.property, a.start + timedelta(hours=1), request_id=uuid.uuid4()
    )
    process(other.operations.get().pk, calendar)
    calendar.events[a.google_id]["start"]["dateTime"] = (a.start + timedelta(hours=1)).isoformat()
    calendar.events[a.google_id]["end"]["dateTime"] = (a.end + timedelta(hours=1)).isoformat()
    calendar.events[a.google_id]["etag"] = "external"
    inspect_appointment(a.pk, calendar)
    a.refresh_from_db()
    _, _, staff = staff_browser()
    submit(
        a.conversation,
        a.property,
        a.start,
        request_id=uuid.uuid4(),
        action="accept",
        appointment=a,
        actor=staff,
    )
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    assert a.status == "review"
    assert a.operations.filter(action="external", status="review").exists()


def test_restore_after_missing_event_reuses_original_id(setup):
    a, calendar = reserve(setup)
    original_id = a.google_id
    del calendar.events[original_id]
    inspect_appointment(a.pk, calendar)
    a.refresh_from_db()
    _, _, staff = staff_browser()
    submit(
        a.conversation,
        a.property,
        a.start,
        request_id=uuid.uuid4(),
        action="restore",
        appointment=a,
        actor=staff,
    )
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    assert a.google_id == original_id and len(calendar.events) == 1 and a.status == "confirmed"


def test_crm_marks_attendance_and_preserves_another_future_booking(setup):
    a, calendar = reserve(setup)
    other = submit(
        a.conversation, a.property, a.start + timedelta(hours=1), request_id=uuid.uuid4()
    )
    process(other.operations.get().pk, calendar)
    Appointment.objects.filter(pk=a.pk).update(
        start=timezone.now() - timedelta(hours=2), end=timezone.now() - timedelta(hours=1)
    )
    staff, headers, _ = staff_browser()
    result = post(
        staff,
        f"/api/crm/appointments/{a.pk}/change",
        {"action": "done", "confirmed": True, "request_id": str(uuid.uuid4())},
        headers,
    )
    assert result.status_code == 200
    a.refresh_from_db()
    a.prospect.refresh_from_db()
    assert a.status == "done" and a.prospect.status == "scheduled"


def test_cancel_remains_allowed_inside_minimum_notice(setup):
    a, calendar = reserve(setup)
    soon = timezone.now() + timedelta(minutes=20)
    Appointment.objects.filter(pk=a.pk).update(start=soon, end=soon + timedelta(hours=1))
    a.refresh_from_db()
    submit(
        a.conversation, a.property, a.start, request_id=uuid.uuid4(), action="cancel", appointment=a
    )
    process(a.operations.order_by("created_at").last().pk, calendar)
    a.refresh_from_db()
    assert a.status == "cancelled"


def test_missing_advisor_uses_default_and_missing_default_keeps_request(setup):
    from datalayer.appointments import slots

    c, p, conn, start = setup
    p.advisor = None
    p.save()
    a = submit(c, p, start, request_id=uuid.uuid4())
    assert a.advisor_id == conn.advisor_id
    Advisor.objects.update(is_default=False)
    result = slots(c, p.pk, start.date().isoformat(), calendar=Calendar())
    assert result["pending"] and Notification.objects.filter(conversation=c).exists()


def test_real_http_adapter_create_move_cancel_uses_conditional_writes(setup):
    c, p, conn, start = setup
    events = {}
    writes = []

    def transport(request):
        assert not connection.in_atomic_block
        assert request.headers["Authorization"] == "Bearer secret-access"
        if request.url.path.endswith("/freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})
        key = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=events[key])
        writes.append(request.method)
        assert request.url.params["sendUpdates"] == "none"
        if request.method == "POST":
            body = json.loads(request.content)
            key = body["id"]
            events[key] = {**body, "etag": "v1", "status": "confirmed"}
        elif request.method == "PATCH":
            assert request.headers["If-Match"] == events[key]["etag"]
            events[key] = {**events[key], **json.loads(request.content), "etag": "v2"}
        else:
            assert request.method == "DELETE" and request.headers["If-Match"] == "v2"
            return httpx.Response(204)
        return httpx.Response(200, json=events[key])

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        calendar = GoogleCalendar(conn, client)
        a = submit(c, p, start, request_id=uuid.uuid4())
        process(a.operations.get().pk, calendar)
        a.refresh_from_db()
        submit(
            c, p, start + timedelta(hours=1), request_id=uuid.uuid4(), action="move", appointment=a
        )
        process(a.operations.order_by("created_at").last().pk, calendar)
        a.refresh_from_db()
        submit(c, p, a.start, request_id=uuid.uuid4(), action="cancel", appointment=a)
        process(a.operations.order_by("created_at").last().pk, calendar)
        a.refresh_from_db()
    assert writes == ["POST", "PATCH", "DELETE"] and a.status == "cancelled"


def test_refresh_token_is_encrypted_and_invalid_grant_disconnects(setup):
    from worker.google_calendar import access_token

    conn = setup[2]
    conn.credentials = encrypt(
        {"access_token": "expired", "refresh_token": "secret-refresh", "expires_at": 0}
    )
    conn.save()

    def success(request):
        assert not connection.in_atomic_block
        assert b"secret-refresh" in request.content
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    with httpx.Client(transport=httpx.MockTransport(success)) as client:
        assert access_token(conn, client) == "new-access"
    conn.refresh_from_db()
    assert (
        "new-access" not in conn.credentials
        and decrypt(conn.credentials)["refresh_token"] == "secret-refresh"
    )
    conn.credentials = encrypt({"refresh_token": "revoked", "expires_at": 0})
    conn.save()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    ) as client:
        with pytest.raises(CalendarError, match="calendar_disconnected"):
            access_token(conn, client)
    conn.refresh_from_db()
    assert not conn.connected


def test_public_confirmation_revalidates_advisor_change(setup):
    c, p, conn, start = setup
    with pytest.raises(ValidationError, match="asesor cambió"):
        submit(c, p, start, request_id=uuid.uuid4(), expected_advisor=999999)
    assert not Appointment.objects.exists()


def test_oauth_log_filter_removes_authorization_codes():
    import logging

    from llm_ops.logging import CalendarCallbackFilter

    record = logging.LogRecord(
        "django.server",
        logging.INFO,
        "",
        1,
        '"%s" 302 %s',
        ("GET /api/calendar/callback?state=private-state&code=private-code HTTP/1.1", 0),
        None,
    )
    CalendarCallbackFilter().filter(record)
    assert "private-code" not in record.getMessage() and "private-state" not in record.getMessage()


def test_visit_without_day_offers_next_available_slots(setup, monkeypatch):
    from datalayer.appointments import date_time

    c, prop, conn, _ = setup
    monkeypatch.setattr(timezone, "now", lambda: date_time("2026-11-06T18:00:00-06:00"))

    class BusyMonday(Calendar):
        def busy(self, start, end):
            assert not connection.in_atomic_block
            return [{"start": "2026-11-09T10:00:00-06:00", "end": "2026-11-09T11:00:00-06:00"}]

    monkeypatch.setattr("datalayer.appointments.GoogleCalendar", lambda connection: BusyMonday())
    result = visit_tool(c.pk, c.revision, "visit_slots", {"property_id": prop.pk})
    assert [s["start"] for s in result["options"]] == [
        "2026-11-09T11:00:00-06:00",
        "2026-11-09T11:30:00-06:00",
        "2026-11-09T12:00:00-06:00",
    ]
    assert not Appointment.objects.exists()


def test_upcoming_slots_paginate_and_respect_explicit_day(setup, monkeypatch):
    from datalayer.appointments import date_time, slots

    c, prop, conn, _ = setup
    monkeypatch.setattr(timezone, "now", lambda: date_time("2026-11-06T18:00:00-06:00"))
    first = slots(c, prop.pk, calendar=Calendar())
    second = slots(c, prop.pk, offset=first["next_offset"], calendar=Calendar())
    assert first["next_offset"] == 3
    assert not ({s["start"] for s in first["options"]} & {s["start"] for s in second["options"]})
    specified = slots(c, prop.pk, "2026-11-10", calendar=Calendar())
    assert all(s["start"].startswith("2026-11-10") for s in specified["options"])


def test_upcoming_slots_skip_full_day_and_stop_at_horizon(setup, monkeypatch):
    from datalayer.appointments import date_time, slots

    c, prop, conn, _ = setup
    monkeypatch.setattr(timezone, "now", lambda: date_time("2026-11-06T18:00:00-06:00"))
    calendar = Calendar()
    calendar.occupied = [{"start": "2026-11-09T00:00:00-06:00", "end": "2026-11-10T00:00:00-06:00"}]
    result = slots(c, prop.pk, calendar=calendar)
    assert all(s["start"].startswith("2026-11-10") for s in result["options"])
    policy = booking_policy()
    policy.horizon_days = 3
    policy.save()
    assert slots(c, prop.pk, calendar=calendar)["options"] == []


def test_whatsapp_button_confirms_once_and_cannot_confirm_another_conversation(setup):
    from datalayer.models import WhatsAppEvent
    from datalayer.whatsapp import process_event

    c, prop, conn, start = setup
    c.channel, c.whatsapp_sender, c.browser_id = "whatsapp", c.declared_phone.lstrip("+"), None
    c.last_whatsapp_at = timezone.now()
    c.save()
    proposal = visit_tool(
        c.pk,
        c.revision,
        "prepare_visit",
        {"action": "create", "property_id": prop.pk, "start": start.isoformat()},
    )["proposal"]
    data = {
        "id": "wamid.button",
        "from": c.whatsapp_sender,
        "timestamp": str(int(timezone.now().timestamp())),
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "id": "ignored",
            "button_reply": {"id": "visit:" + proposal["id"], "title": "Forged title"},
        },
    }
    event = WhatsAppEvent.objects.create(
        key="button-one", payload={"kind": "messages", "data": data}
    )
    process_event(event.pk)
    event.refresh_from_db()
    assert event.status == "processed" and Appointment.objects.count() == 1
    another = WhatsAppEvent.objects.create(
        key="button-two", payload={"kind": "messages", "data": data}
    )
    process_event(another.pk)
    assert Appointment.objects.count() == 1
    foreign = Conversation.objects.create(
        channel="whatsapp",
        whatsapp_sender="523398765432",
        browser_id=None,
        prospect=c.prospect,
        declared_phone=c.declared_phone,
    )
    data = {**data, "from": foreign.whatsapp_sender}
    other = WhatsAppEvent.objects.create(
        key="button-other", payload={"kind": "messages", "data": data}
    )
    process_event(other.pk)
    assert Appointment.objects.count() == 1
    assert not foreign.appointments.exists()


def test_whatsapp_calendar_result_is_a_public_message_without_error_codes(setup):
    from datalayer.appointments import notify_appointment
    from datalayer.models import WhatsAppDelivery

    c, prop, conn, start = setup
    c.channel, c.whatsapp_sender = "whatsapp", c.declared_phone.lstrip("+")
    c.save()
    a, calendar = reserve(setup)
    assert WhatsAppDelivery.objects.count() == 1
    delivery = WhatsAppDelivery.objects.get()
    assert "ya quedó agendada" in delivery.message.text
    a.status = "review"
    a.save()
    notify_appointment(a, "review-key", "INTERNAL_ERROR_DO_NOT_SHOW")
    assert "INTERNAL_ERROR" not in WhatsAppDelivery.objects.latest("created_at").message.text


def test_telegram_appointment_uses_event_snapshot_without_interests_and_keeps_it_on_retry(
    setup, settings
):
    from worker.telegram import claim_notification, finish_notification

    settings.TELEGRAM_BOT_TOKEN = "test-secret"
    settings.PUBLIC_BASE_URL = "https://sandbox.elmenlabs.com"
    c, prop, conn, start = setup
    c.channel = "whatsapp"
    c.save()
    conn.advisor.telegram_chat_id = "12345"
    conn.advisor.save()
    a, _ = reserve(setup)
    event = Notification.objects.get(advisor=conn.advisor)
    assert not c.interests.exists()
    payload = claim_notification(event.pk)
    text = payload["text"]
    assert text.startswith("Visita confirmada\nInformación\n")
    assert prop.title in text and "hora de Guadalajara" in text
    assert "+00:00" not in text and "no proporcionado" not in text
    assert "sin propiedad" not in text and "sin verificar" not in text
    assert "sandbox.elmenlabs.com/crm" in text
    assert "_visit" not in payload
    finish_notification(event.pk, "failed", "telegram_400")
    assert claim_notification(event.pk)["text"] == text


@pytest.mark.parametrize("action", ["move", "cancel", None])
def test_harness_only_sends_a_button_for_an_explicit_validated_proposal(setup, action):
    from datalayer.models import AppointmentProposal, Message, WhatsAppDelivery
    from harness.runtime import attend
    from tests.test_turn_contract import final

    c, prop, conn, start = setup
    appointment, calendar = reserve(setup)
    c.channel, c.whatsapp_sender, c.revision = "whatsapp", c.declared_phone.lstrip("+"), 1
    c.last_whatsapp_at = timezone.now()
    c.save()
    Message.objects.create(conversation=c, role="user", text="La opción 3 me funciona")
    text = "Preparé el cambio de tu visita. Pulsa el botón de WhatsApp para confirmar el cambio."
    responses = []
    if action:
        async def confirmation():
            proposal = await AppointmentProposal.objects.aget(conversation=c)
            return response(final(text, control={"kind": "visit", "proposal_id": str(proposal.pk)},
                                  pending={"kind": "visit_confirmation", "subject": "confirmar el cambio"}))

        responses.extend(
            [
                response(
                    {
                        "type": "tool_use",
                        "id": "prepare",
                        "name": "prepare_visit",
                        "input": {
                            "action": action,
                            "appointment_id": str(appointment.pk),
                            "start": (start + timedelta(hours=2)).isoformat(),
                        },
                    }
                ),
                confirmation,
            ]
        )
    else:
        invalid = final(text, pending={"kind": "visit_confirmation", "subject": "confirmar el cambio"})
        responses = [response(invalid), response(invalid)]
    client = ScriptedClient(responses)

    async def run():
        try:
            await attend(str(c.pk), client, group_messages=False)
        finally:
            await sync_to_async(connections.close_all)()

    asyncio.run(run())
    delivery = WhatsAppDelivery.objects.get(conversation=c)
    if action:
        proposal = AppointmentProposal.objects.get(conversation=c)
        assert proposal.action == action
        assert delivery.payload["type"] == "interactive"
        assert delivery.payload["interactive"]["action"]["buttons"][0]["reply"][
            "id"
        ] == "visit:" + str(proposal.pk)
        assert len(client.calls) == 2
    else:
        assert not AppointmentProposal.objects.filter(conversation=c).exists()
        assert not delivery.message.is_error
        assert "botón" not in delivery.message.text
        assert len(client.calls) == 2
    assert c.messages.filter(role="assistant").count() == 1
    appointment.refresh_from_db()
    assert appointment.start == start and appointment.status == "confirmed"
