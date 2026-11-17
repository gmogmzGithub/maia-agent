"""Durable calendar operations and reconciliation, without open SQL/network transactions."""

import hashlib
from datetime import timedelta
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.appointments import (
    booking_policy,
    conflicts,
    date_time,
    google_free,
    notify_appointment,
    reconcile_prospect,
    validate_slot,
)
from datalayer.models import Appointment, AppointmentOperation
from worker.google_calendar import CalendarError, GoogleCalendar


def projection(event):
    return {
        key: event.get(key)
        for key in (
            "id",
            "etag",
            "status",
            "summary",
            "location",
            "start",
            "end",
            "extendedProperties",
        )
    }


def event_times(event):
    return date_time(event["start"]["dateTime"]), date_time(event["end"]["dateTime"])


def event_matches(event, operation):
    try:
        return (
            event.get("status") != "cancelled"
            and event_times(event) == (operation.start, operation.end)
            and event.get("extendedProperties", {}).get("private", {}).get("maia_operation")
            == str(operation.pk)
        )
    except (KeyError, ValidationError):
        return False


def body_for(operation):
    a = operation.appointment
    return {
        "summary": "Maia · " + a.property.title,
        "location": a.property.public_address,
        "description": "Visita coordinada por Maia. " + str(a.pk),
        "start": {"dateTime": operation.start.isoformat(), "timeZone": "America/Mexico_City"},
        "end": {"dateTime": operation.end.isoformat(), "timeZone": "America/Mexico_City"},
        "transparency": "opaque",
        "extendedProperties": {
            "private": {"maia_appointment": str(a.pk), "maia_operation": str(operation.pk)}
        },
    }


@transaction.atomic
def finish(operation_id, event=None, *, cancelled=False):
    booking_policy(lock=True)
    op = (
        AppointmentOperation.objects.select_for_update()
        .select_related("appointment__connection")
        .get(pk=operation_id)
    )
    if op.status == "completed":
        return
    a = op.appointment
    if not a.connection.connected or a.connection.generation != a.connection_generation:
        review(op, "calendar_connection_changed", event)
        return
    if cancelled:
        a.status = "cancelled"
    else:
        a.status, a.start, a.end = "confirmed", op.start, op.end
        a.google_id, a.etag = op.google_id, event["etag"]
    a.observed, a.checked_at = projection(event) if event else {}, timezone.now()
    a.save()
    op.status, op.error_code = "completed", ""
    op.save(update_fields=["status", "error_code", "updated_at"])
    a.operations.filter(status="review").exclude(pk=op.pk).update(status="resolved")
    reconcile_prospect(a.prospect_id, op.actor)
    from datalayer.appointments import visit_time

    headline = (
        "Visita cancelada"
        if cancelled
        else ("Visita reprogramada" if op.action == "move" else "Visita confirmada")
    )
    summary = f"{headline}: {a.property.title}, {visit_time(a.start, a.end)}"
    notify_appointment(a, str(op.pk), summary, headline=headline)
    # Browser displays durable status; do not ask the LLM to invent confirmation.
    from datalayer.models import ProspectEvent

    ProspectEvent.objects.create(prospect=a.prospect, actor=op.actor, description=summary)


@transaction.atomic
def review(op, code, event=None):
    op.status, op.error_code = "review", code
    op.save(update_fields=["status", "error_code", "updated_at"])
    a = op.appointment
    a.status = "review"
    if event is not None:
        a.observed = projection(event)
    a.save(update_fields=["status", "observed", "updated_at"])
    notify_appointment(a, "review:" + str(op.pk), "Cita requiere revisión: " + code)


@transaction.atomic
def failed(op, code):
    op.status, op.error_code = "failed", code
    op.save(update_fields=["status", "error_code", "updated_at"])
    if op.action == "create":
        op.appointment.status = "failed"
        op.appointment.save(update_fields=["status", "updated_at"])
    notify_appointment(
        op.appointment, "failed:" + str(op.pk), "Solicitud de cita sin confirmar: " + code
    )


def process(operation_id, calendar=None):
    with transaction.atomic():
        op = (
            AppointmentOperation.objects.select_for_update()
            .select_related(
                "appointment__connection",
                "appointment__property",
                "appointment__advisor",
                "appointment__prospect",
                "appointment__conversation",
            )
            .get(pk=operation_id)
        )
        if op.status not in {"queued", "verifying", "running"}:
            return
        if op.status == "running" and op.updated_at > timezone.now() - timedelta(seconds=50):
            return
        if op.status == "verifying" and op.verify_after and op.verify_after > timezone.now():
            return
        op.status = "running"
        op.attempts += 1
        op.save(update_fields=["status", "attempts", "updated_at"])
    a = op.appointment
    calendar = calendar or GoogleCalendar(a.connection)
    recovering = bool(op.sent_at)
    try:
        if a.connection_generation != a.connection.generation or not a.connection.connected:
            raise CalendarError("calendar_disconnected")
        current = None
        if op.action != "create" or op.sent_at:
            try:
                current = calendar.event(op.google_id)
            except CalendarError as exc:
                if exc.status not in {404, 410}:
                    raise
                # Missing is not success. Do not release a hold on an ambiguous 404.
                if op.sent_at and not (exc.status == 410 and op.action == "cancel"):
                    raise CalendarError("event_result_unknown") from None
                current = {"status": "cancelled"} if exc.status == 410 else {"missing": True}
                if current.get("missing") and op.action != "restore":
                    review(op, "event_missing_requires_review", current)
                    return
        if op.sent_at:
            if current and op.action == "cancel" and current.get("status") == "cancelled":
                finish(op.pk, current, cancelled=True)
            elif current and event_matches(current, op):
                finish(op.pk, current)
            else:
                raise CalendarError("event_result_unknown")
            return
        if op.action == "accept":
            if current.get("status") == "cancelled":
                finish(op.pk, current, cancelled=True)
                return
            start, end = event_times(current)
            if not google_free(
                calendar, start, end, existing=SimpleNamespace(start=start, end=end)
            ):
                raise CalendarError("calendar_slot_unavailable")
            with transaction.atomic():
                policy = booking_policy(lock=True)
                validate_slot(a.property, start, end, policy, duration=a.duration)
                if conflicts(
                    a.property,
                    a.advisor,
                    a.connection,
                    a.prospect_id,
                    start,
                    end,
                    exclude=a.pk,
                    exclude_operation=op.pk,
                    exclude_appointment_operations=a.pk,
                ):
                    raise CalendarError("local_conflict")
                op.start, op.end = start, end
                op.save(update_fields=["start", "end", "updated_at"])
            finish(op.pk, current)
            return
        if op.action != "create" and op.action != "restore":
            if current.get("status") == "cancelled" or current.get("etag") != a.etag:
                review(op, "external_change", current)
                return
        if op.action != "cancel":
            validate_slot(a.property, op.start, op.end, booking_policy(), duration=a.duration)
            occupied_event = None
            if current and current.get("status") != "cancelled" and not current.get("missing"):
                occupied_start, occupied_end = event_times(current)
                occupied_event = SimpleNamespace(start=occupied_start, end=occupied_end)
            if not google_free(
                calendar,
                op.start,
                op.end,
                existing=occupied_event,
            ):
                raise CalendarError("calendar_slot_unavailable")
        if op.action == "restore" and current.get("status") == "cancelled":
            # A deliberate restoration is a new business operation, not a retry.
            op.google_id = op.pk.hex
            op.save(update_fields=["google_id", "updated_at"])
            current = None
        elif op.action == "restore" and current.get("missing"):
            # Reuse the original ID after an ambiguous 404. A delayed original
            # creation cannot become a second event under another identifier.
            current = None
        with transaction.atomic():
            locked = AppointmentOperation.objects.select_for_update().get(pk=op.pk)
            locked.sent_at = timezone.now()
            locked.save(update_fields=["sent_at", "updated_at"])
            op.sent_at = locked.sent_at
        if op.action == "cancel":
            calendar.delete(op.google_id, current["etag"])
            finish(op.pk, cancelled=True)
        else:
            body = body_for(op)
            if op.action == "create" or current is None:
                result = calendar.create({"id": op.google_id, **body})
            else:
                result = calendar.change(op.google_id, body, current["etag"])
            if not event_matches(result, op) or not result.get("etag"):
                raise CalendarError("event_result_unknown")
            finish(op.pk, result)
    except CalendarError as exc:
        if exc.code in {
            "calendar_disconnected",
            "calendar_connection_changed",
            "calendar_key_unavailable",
        }:
            review(op, exc.code)
        elif exc.status == 412 and not recovering:
            review(op, "external_change")
        elif recovering or (
            op.sent_at and (exc.status == 409 or exc.status == 0 or exc.status >= 500)
        ):
            op.status, op.error_code = "verifying", exc.code
            op.verify_after = timezone.now() + timedelta(minutes=1)
            op.save(update_fields=["status", "error_code", "verify_after", "updated_at"])
            if op.attempts >= 6:
                review(op, "verification_required")
        else:
            failed(op, exc.code)
    except (ValidationError, KeyError, TypeError):
        if op.sent_at:
            review(op, "invalid_google_result")
        else:
            failed(op, "slot_rules_changed")


def inspect_appointment(appointment_id, calendar=None):
    a = Appointment.objects.select_related("connection", "property", "advisor", "prospect").get(
        pk=appointment_id
    )
    if (
        a.status != "confirmed"
        or a.operations.filter(status__in=["queued", "running", "verifying", "review"]).exists()
    ):
        return
    calendar = calendar or GoogleCalendar(a.connection)
    inspected_etag, inspected_id = a.etag, a.google_id
    try:
        event = calendar.event(a.google_id)
        if event.get("etag") == a.etag and event.get("status") != "cancelled":
            Appointment.objects.filter(pk=a.pk).update(checked_at=timezone.now())
            return
    except CalendarError as exc:
        if exc.status not in {404, 410} and exc.code != "calendar_disconnected":
            return
        event = {"unavailable": exc.code}
    with transaction.atomic():
        booking_policy(lock=True)
        a = Appointment.objects.select_for_update().get(pk=a.pk)
        if (
            a.status != "confirmed"
            or a.etag != inspected_etag
            or a.google_id != inspected_id
            or a.operations.filter(status__in=["queued", "running", "verifying", "review"]).exists()
        ):
            return
        a.status, a.observed, a.checked_at = (
            "review",
            projection(event) if "id" in event else event,
            timezone.now(),
        )
        a.save(update_fields=["status", "observed", "checked_at", "updated_at"])
        import uuid

        try:
            observed_start, observed_end = event_times(event)
            if observed_start >= observed_end:
                raise KeyError
        except (KeyError, TypeError, ValidationError):
            observed_start, observed_end = a.start, a.end
        AppointmentOperation.objects.create(
            appointment=a,
            request_id=uuid.uuid4(),
            action="external",
            status="review",
            start=observed_start,
            end=observed_end,
            google_id=a.google_id,
            error_code="external_change",
        )
        notify_appointment(
            a,
            "external:"
            + str(a.pk)
            + ":"
            + hashlib.sha256(str(event.get("etag", "missing")).encode()).hexdigest()[:16],
            "Cambio externo detectado. Revisa la cita en el CRM.",
        )


def maintain():
    from worker.dispatch import enqueue_appointment, enqueue_inspection

    now = timezone.now()
    with transaction.atomic():
        for op in AppointmentOperation.objects.filter(
            status__in=["queued", "running", "verifying"],
            updated_at__lt=now - timedelta(seconds=50),
        ):
            enqueue_appointment(op.pk)
        for a in Appointment.objects.filter(status="confirmed", end__gt=now):
            if a.checked_at is None or a.checked_at < now - timedelta(minutes=5):
                enqueue_inspection(a.pk)
