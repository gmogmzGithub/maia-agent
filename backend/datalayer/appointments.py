"""Deterministic booking rules. Short SQL transactions; Google calls stay outside."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from datalayer.inventory import public_inventory
from datalayer.models import (
    Advisor,
    Appointment,
    AppointmentOperation,
    BookingPolicy,
    CalendarConnection,
    Conversation,
    Notification,
    Property,
    Prospect,
    ProspectEvent,
)
from worker.google_calendar import CalendarError, GoogleCalendar

LOCAL = ZoneInfo("America/Mexico_City")
ACTIVE_OPERATIONS = ["queued", "running", "verifying", "review"]
ACTIVE_APPOINTMENTS = ["pending", "confirmed", "review"]


def visit_time(start, end=None):
    start = start.astimezone(LOCAL)
    days = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    date = f"{days[start.weekday()]} {start.day} de {months[start.month - 1]}"
    if start.year != timezone.localtime().year:
        date += f" de {start.year}"
    return (
        f"{date}, de {start:%H:%M} a {end.astimezone(LOCAL):%H:%M}"
        if end
        else f"{date} a las {start:%H:%M}"
    )


def reject(message):
    raise ValidationError({"appointment": message})


def date_time(value):
    try:
        dt = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        return dt.replace(tzinfo=LOCAL) if timezone.is_naive(dt) else dt.astimezone(LOCAL)
    except (ValueError, TypeError, AttributeError):
        reject("Indica fecha y hora válidas, en horario de Guadalajara.")


def booking_policy(lock=False):
    BookingPolicy.objects.get_or_create(pk=1)
    query = BookingPolicy.objects.select_for_update() if lock else BookingPolicy.objects
    return query.get(pk=1)


def visit_advisor(prop):
    return prop.advisor or Advisor.objects.filter(is_default=True).first()


def connection_for(advisor):
    conn = CalendarConnection.objects.filter(advisor=advisor, connected=True).first()
    if conn is None:
        raise CalendarError("calendar_disconnected")
    return conn


def validate_windows(windows):
    if not isinstance(windows, list) or len(windows) > 28:
        reject("Configura hasta 28 ventanas semanales.")
    seen = []
    for window in windows:
        if not isinstance(window, dict) or set(window) != {"day", "start", "end"}:
            reject("Cada ventana requiere día, inicio y fin.")
        try:
            day = window["day"]
            start = datetime.strptime(window["start"], "%H:%M").time()
            end = datetime.strptime(window["end"], "%H:%M").time()
            if (
                type(day) is not int
                or not 0 <= day <= 6
                or start >= end
                or start.strftime("%H:%M") != window["start"]
                or end.strftime("%H:%M") != window["end"]
            ):
                raise ValueError
        except (ValueError, TypeError):
            reject("Revisa los días y horarios de las ventanas.")
        if any(d == day and a < end and b > start for d, a, b in seen):
            reject("Las ventanas de un mismo día no deben superponerse.")
        seen.append((day, start, end))
    return windows


def validate_slot(prop, start, end, policy, *, duration=None):
    start, end = date_time(start), date_time(end)
    if not public_inventory().filter(pk=prop.pk).exists():
        reject("La propiedad ya no admite nuevas reservas.")
    expected = duration or prop.visit_duration
    if end - start != timedelta(minutes=expected):
        reject("La duración cambió. Consulta horarios nuevamente.")
    if start.minute % 30 or start.second or start.microsecond:
        reject("Las citas comienzan cada 30 minutos.")
    now = timezone.now()
    if start < now + timedelta(hours=policy.notice_hours):
        reject("El horario no cumple la anticipación mínima.")
    if start > now + timedelta(days=policy.horizon_days):
        reject("La fecha supera el horizonte de reserva. Solicita atención del asesor.")
    if not any(
        w["day"] == start.weekday()
        and start.date() == end.date()
        and w["start"] <= start.strftime("%H:%M")
        and w["end"] >= end.strftime("%H:%M")
        for w in validate_windows(prop.visit_windows)
    ):
        reject("La cita debe caber completa en una ventana de la propiedad.")


def conflicts(
    prop,
    advisor,
    conn,
    prospect_id,
    start,
    end,
    *,
    exclude=None,
    exclude_operation=None,
    exclude_appointment_operations=None,
):
    resource = (
        Q(property_id=prop.pk) | Q(advisor_id=advisor.pk) | Q(connection__subject=conn.subject)
    )
    if prospect_id:
        resource |= Q(prospect_id=prospect_id)
    appointments = Appointment.objects.filter(
        resource, status__in=ACTIVE_APPOINTMENTS, start__lt=end, end__gt=start
    )
    if exclude:
        appointments = appointments.exclude(pk=exclude)
    if appointments.exists():
        return True
    resource = (
        Q(appointment__property_id=prop.pk)
        | Q(appointment__advisor_id=advisor.pk)
        | Q(appointment__connection__subject=conn.subject)
    )
    if prospect_id:
        resource |= Q(appointment__prospect_id=prospect_id)
    operations = AppointmentOperation.objects.filter(
        resource, status__in=ACTIVE_OPERATIONS, start__lt=end, end__gt=start
    )
    if exclude_operation:
        operations = operations.exclude(pk=exclude_operation)
    if exclude_appointment_operations:
        operations = operations.exclude(appointment_id=exclude_appointment_operations)
    return operations.exists()


def google_free(calendar, start, end, *, existing=None):
    # freeBusy cannot exclude one event. Ignore occupation wholly inside our
    # verified event. This does not provide atomic exclusion of outside edits.
    for interval in calendar.busy(start, end):
        a, b = date_time(interval["start"]), date_time(interval["end"])
        if a < end and b > start:
            if existing and existing.start <= a and existing.end >= b:
                continue
            return False
    return True


def appointment_output(appointment, *, staff=False):
    from datalayer.public_history import public_title
    operations = appointment.operations.order_by("-created_at")
    last = operations.first()
    result = {
        "id": str(appointment.pk),
        "property_id": appointment.property_id,
        "property_title": appointment.property.title if staff else public_title(appointment.property),
        "advisor": appointment.advisor.name,
        "start": appointment.start.isoformat(),
        "end": appointment.end.isoformat(),
        "timezone": str(LOCAL),
        "status": appointment.status,
        "operation_status": last.status if last else "",
        "operation_error": last.error_code if last else "",
    }
    if staff:
        result.update(
            prospect_id=appointment.prospect_id,
            conversation_id=str(appointment.conversation_id),
            observed=appointment.observed,
            operations=[
                {
                    "id": str(o.pk),
                    "action": o.action,
                    "status": o.status,
                    "error_code": o.error_code,
                    "start": o.start.isoformat(),
                    "end": o.end.isoformat(),
                    "attempts": o.attempts,
                }
                for o in operations
            ],
        )
    return result


def proposal_output(proposal):
    from datalayer.public_history import public_title

    return {
        "id": str(proposal.pk),
        "action": proposal.action,
        "appointment_id": str(proposal.appointment_id) if proposal.appointment_id else None,
        "property_id": proposal.property_id,
        "property_title": public_title(proposal.property),
        "advisor": proposal.advisor.name,
        "start": proposal.start.isoformat(),
        "end": proposal.end.isoformat(),
        "timezone": str(LOCAL),
    }


def notify_appointment(appointment, key, summary, *, headline=None, notify_client=True):
    from datalayer.public_history import public_title
    from worker.dispatch import enqueue_notification

    if notify_client and appointment.conversation.channel == "whatsapp":
        from datalayer.whatsapp import reply

        if not appointment.conversation.whatsapp_deliveries.filter(
            event_key=f"visit-result:{key}"
        ).exists():
            when = visit_time(appointment.start, appointment.end)
            if appointment.status == "cancelled":
                public_summary = f"Listo, tu visita a {public_title(appointment.property)} quedó cancelada. Cuando quieras retomarla, escríbeme."
            elif appointment.status == "confirmed":
                public_summary = f"Tu visita a {public_title(appointment.property)} ya quedó agendada para el {when}, hora de Guadalajara. Te recibirá {appointment.advisor.name}."
            else:
                public_summary = "Todavía no pude completar el cambio de tu visita. Dejé la solicitud para que tu asesor la revise."
            reply(appointment.conversation, public_summary, f"visit-result:{key}")

    recipients = {appointment.advisor_id, appointment.prospect.advisor_id} - {None}
    for advisor_id in recipients:
        notice, created = Notification.objects.get_or_create(
            event_key=f"visit:{key}:{advisor_id}",
            defaults={
                "conversation": appointment.conversation,
                "advisor_id": advisor_id,
                "reason": "appointment",
                "summary": summary[:1000],
                "payload": {
                    "_visit": {
                        "headline": headline or "Visita requiere atención",
                        "property": appointment.property.title,
                        "when": visit_time(appointment.start, appointment.end),
                        "attention": headline is None,
                    }
                },
            },
        )
        if created:
            enqueue_notification(notice.pk)


def pending_request(conversation, summary):
    from datalayer.prospects import notice

    with transaction.atomic():
        conversation.human_requested = True
        conversation.save(update_fields=["human_requested", "updated_at"])
        notice(
            conversation,
            "human_request",
            f"visit-request:{conversation.pk}:{conversation.revision}",
            summary,
        )
    return {"pending": True, "detail": "Solicitud pendiente en CRM; no hay cita confirmada."}


def slots(conversation, property_id, day=None, *, appointment=None, offset=0, calendar=None):
    prop = public_inventory().filter(pk=property_id).first()
    if prop is None:
        reject("La propiedad ya no está disponible para nuevas visitas.")
    advisor = appointment.advisor if appointment else visit_advisor(prop)
    if not advisor:
        return pending_request(
            conversation, "Solicitud de visita: falta asesor de la propiedad o predeterminado."
        )
    policy = booking_policy()
    now = timezone.now().astimezone(LOCAL)
    start_day = (
        date_time(day + "T00:00:00")
        if day
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    end_range = (
        start_day + timedelta(days=1)
        if day
        else (now + timedelta(days=policy.horizon_days + 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    )
    if (
        start_day.date()
        > (timezone.now().astimezone(LOCAL) + timedelta(days=policy.horizon_days)).date()
    ):
        return pending_request(conversation, "Solicitud de visita fuera del horizonte: " + day)
    try:
        conn = connection_for(advisor)
        calendar = calendar or GoogleCalendar(conn)
        busy = calendar.busy(start_day, end_range)
    except CalendarError:
        return pending_request(
            conversation, "Solicitud de visita pendiente: Google Calendar no está disponible."
        )
    candidates = []
    for minute in range(0, int((end_range - start_day).total_seconds() // 60), 30):
        start = start_day + timedelta(minutes=minute)
        end = start + timedelta(
            minutes=appointment.duration if appointment else prop.visit_duration
        )
        try:
            validate_slot(
                prop, start, end, policy, duration=appointment.duration if appointment else None
            )
        except ValidationError:
            continue
        if conflicts(
            prop,
            advisor,
            conn,
            conversation.prospect_id,
            start,
            end,
            exclude=appointment.pk if appointment else None,
        ):
            continue
        if any(date_time(i["start"]) < end and date_time(i["end"]) > start for i in busy):
            continue
        candidates.append({"start": start.isoformat(), "end": end.isoformat()})
        if len(candidates) > offset + 3:
            break
    return {
        "options": candidates[offset : offset + 3],
        "next_offset": offset + 3 if len(candidates) > offset + 3 else None,
        "timezone": str(LOCAL),
        "advisor": advisor.name,
        "detail": "Ofrece estos horarios concretos y pregunta cuál le funciona. Son opciones sin reserva. Si no hay opciones, registra su preferencia para el asesor; no inventes horarios.",
    }


@transaction.atomic
def submit(
    conversation,
    prop,
    start,
    *,
    request_id,
    action="create",
    appointment=None,
    actor=None,
    expected_end=None,
    expected_advisor=None,
):
    from worker.dispatch import enqueue_appointment

    # Global short lock keeps the small pilot simple. No Google call under it.
    policy = booking_policy(lock=True)
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    if not conversation.prospect_id or not conversation.declared_phone:
        reject("Confirma primero el celular en esta conversación.")
    existing = AppointmentOperation.objects.filter(request_id=request_id).first()
    if existing:
        if existing.appointment.conversation_id != conversation.pk or existing.action != action:
            reject("La solicitud no pertenece a esta conversación.")
        return existing.appointment
    if appointment:
        appointment = Appointment.objects.select_for_update().get(pk=appointment.pk)
        if appointment.conversation_id != conversation.pk:
            reject("Gestiona la cita desde su conversación original o mediante el asesor.")
        if (
            appointment.operations.filter(status__in=ACTIVE_OPERATIONS)
            .exclude(status="review" if action in {"accept", "restore"} else "")
            .exists()
        ):
            reject("La cita tiene una operación pendiente de resolver.")
        if action not in {"accept", "restore"} and appointment.status != "confirmed":
            reject("Esta cita no admite cambios automáticos.")
        if action in {"accept", "restore"} and (not actor or appointment.status != "review"):
            reject("La resolución requiere revisión del asesor.")
        advisor, conn = appointment.advisor, appointment.connection
        prop = appointment.property
    else:
        prop = Property.objects.get(pk=prop.pk)
        advisor = visit_advisor(prop)
        if not advisor:
            raise CalendarError("advisor_not_configured")
        conn = connection_for(advisor)
    if expected_advisor and advisor.pk != expected_advisor:
        reject("El asesor cambió. Consulta el horario y confirma nuevamente.")
    start = date_time(start)
    end = start + timedelta(minutes=appointment.duration if appointment else prop.visit_duration)
    if expected_end and end != date_time(expected_end):
        reject("La duración cambió. Consulta horarios nuevamente.")
    if action not in {"cancel", "accept"}:
        validate_slot(
            prop, start, end, policy, duration=appointment.duration if appointment else None
        )
        if conflicts(
            prop,
            advisor,
            conn,
            conversation.prospect_id,
            start,
            end,
            exclude=appointment.pk if appointment else None,
            exclude_appointment_operations=appointment.pk
            if appointment and action in {"accept", "restore"}
            else None,
        ):
            reject("Ese horario ya no está disponible. Elige otro.")
    if not appointment:
        import uuid

        appointment = Appointment.objects.create(
            conversation=conversation,
            prospect=conversation.prospect,
            property=prop,
            advisor=advisor,
            connection=conn,
            connection_generation=conn.generation,
            start=start,
            end=end,
            duration=prop.visit_duration,
            google_id=uuid.uuid4().hex,
        )
    operation = AppointmentOperation.objects.create(
        appointment=appointment,
        request_id=request_id,
        action=action,
        start=start,
        end=end,
        google_id=appointment.google_id,
        actor=actor,
    )
    from datalayer.models import FollowupCycle

    FollowupCycle.objects.filter(
        prospect_id=conversation.prospect_id, closed_at__isnull=True
    ).update(suspended=True, reason="appointment")
    enqueue_appointment(operation.pk)
    return appointment


@transaction.atomic
def reconcile_prospect(prospect_id, actor=None):
    prospect = Prospect.objects.select_for_update().get(pk=prospect_id)
    future = prospect.appointments.filter(status="confirmed", start__gt=timezone.now()).exists()
    target = "scheduled" if future else "attending"
    if prospect.status != target:
        prospect.status = target
        prospect.save(update_fields=["status", "updated_at"])
        ProspectEvent.objects.create(
            prospect=prospect,
            actor=actor,
            description="Etapa actualizada por resultado de cita: " + target,
        )
