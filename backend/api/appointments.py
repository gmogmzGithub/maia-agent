import uuid
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import SessionAuthIsStaff
from pydantic import Field

from api.auth import BrowserAuth, browser_id
from datalayer.appointments import (
    appointment_output,
    booking_policy,
    date_time,
    notify_appointment,
    pending_request,
    reconcile_prospect,
    slots,
    submit,
    validate_windows,
)
from datalayer.conversations import conversation_output
from datalayer.models import Appointment, AppointmentProposal, Conversation, Property
from worker.google_calendar import CalendarError

crm = Router(auth=SessionAuthIsStaff())
chat = Router(auth=BrowserAuth())


class PolicyInput(Schema):
    notice_hours: int = Field(ge=0, le=168)
    horizon_days: int = Field(ge=1, le=90)


class RulesInput(Schema):
    duration: int = Field(ge=15, le=480)
    windows: list[dict] = Field(max_length=28)


class BookingInput(Schema):
    conversation_id: uuid.UUID
    property_id: int = Field(gt=0)
    start: str
    request_id: uuid.UUID
    confirmed: bool
    duration: int | None = Field(default=None, ge=15, le=480)


class ChangeInput(Schema):
    action: str
    start: str | None = None
    request_id: uuid.UUID
    confirmed: bool


class ConfirmProposal(Schema):
    proposal_id: uuid.UUID
    confirmed: bool


def own_conversation(request, conversation_id):
    return get_object_or_404(Conversation, pk=conversation_id, browser_id=browser_id(request))


@crm.get("/booking-policy", response=dict)
def policy(request):
    value = booking_policy()
    return {"notice_hours": value.notice_hours, "horizon_days": value.horizon_days}


@crm.put("/booking-policy", response=dict)
def update_policy(request, data: PolicyInput):
    with transaction.atomic():
        value = booking_policy(lock=True)
        value.notice_hours, value.horizon_days = data.notice_hours, data.horizon_days
        value.save()
    return policy(request)


@crm.get("/properties/{property_id}/visits", response=dict)
def property_visits(request, property_id: int):
    prop = get_object_or_404(Property, pk=property_id)
    return {"duration": prop.visit_duration, "windows": prop.visit_windows}


@crm.put("/properties/{property_id}/visits", response=dict)
def update_property_visits(request, property_id: int, data: RulesInput):
    validate_windows(data.windows)
    with transaction.atomic():
        booking_policy(lock=True)
        prop = get_object_or_404(Property.objects.select_for_update(), pk=property_id)
        prop.visit_duration, prop.visit_windows = data.duration, data.windows
        prop.save(update_fields=["visit_duration", "visit_windows", "updated_at"])
    return property_visits(request, property_id)


@crm.get("/appointments", response=list[dict])
def appointments(request):
    return [
        appointment_output(a, staff=True)
        for a in Appointment.objects.select_related("property", "advisor").order_by("-created_at")
    ]


@crm.get("/appointments/options", response=dict)
def staff_options(
    request, conversation_id: uuid.UUID, property_id: int, day: str | None = None, offset: int = 0
):
    if offset < 0 or offset > 100:
        raise HttpError(422, "Página inválida.")
    return slots(
        get_object_or_404(Conversation, pk=conversation_id), property_id, day, offset=offset
    )


@crm.post("/appointments", response=dict)
def create_appointment(request, data: BookingInput):
    if not data.confirmed:
        raise HttpError(422, "Confirma propiedad, fecha y horario antes de reservar.")
    conversation = get_object_or_404(Conversation, pk=data.conversation_id)
    prop = get_object_or_404(Property, pk=data.property_id)
    try:
        a = submit(
            conversation,
            prop,
            data.start,
            request_id=data.request_id,
            actor=request.user,
            expected_end=date_time(data.start) + timedelta(minutes=data.duration)
            if data.duration
            else None,
        )
    except CalendarError:
        pending_request(
            conversation,
            f"Solicitud de visita a {prop.title}, {data.start}. Falta asesor o conexión de Google.",
        )
        raise
    return appointment_output(a, staff=True)


@crm.post("/appointments/{appointment_id}/change", response=dict)
def change_appointment(request, appointment_id: uuid.UUID, data: ChangeInput):
    a = get_object_or_404(Appointment, pk=appointment_id)
    if not data.confirmed:
        raise HttpError(422, "Confirma el cambio.")
    if data.action in {"done", "no_show"}:
        with transaction.atomic():
            booking_policy(lock=True)
            a = Appointment.objects.select_for_update().get(pk=a.pk)
            if (
                a.status != "confirmed"
                or a.start > timezone.now()
                or a.operations.filter(
                    status__in=["queued", "running", "verifying", "review"]
                ).exists()
            ):
                raise HttpError(409, "La cita no admite registrar asistencia todavía.")
            a.status = data.action
            a.save(update_fields=["status", "updated_at"])
            reconcile_prospect(a.prospect_id, request.user)
            notify_appointment(
                a, f"outcome:{a.pk}:{data.action}", "Resultado de visita: " + data.action
            )
        return appointment_output(a, staff=True)
    if data.action not in {"cancel", "move", "accept", "restore"}:
        raise HttpError(422, "Acción inválida.")
    start = data.start or a.start
    return appointment_output(
        submit(
            a.conversation,
            a.property,
            start,
            request_id=data.request_id,
            action=data.action,
            appointment=a,
            actor=request.user,
        ),
        staff=True,
    )


@chat.get("/{conversation_id}/visits/options", response=dict)
def public_options(
    request, conversation_id: uuid.UUID, property_id: int, day: str | None = None, offset: int = 0
):
    if not 0 <= offset <= 100:
        raise HttpError(422, "Página inválida.")
    return slots(own_conversation(request, conversation_id), property_id, day, offset=offset)


@chat.post("/{conversation_id}/visits/confirm", response=dict)
def confirm_visit(request, conversation_id: uuid.UUID, data: ConfirmProposal):
    conversation = own_conversation(request, conversation_id)
    try:
        a = confirm_proposal(conversation, data)
    except CalendarError:
        pending_request(
            conversation, "Confirmación de visita pendiente: falta asesor o conexión de Google."
        )
        raise
    return {"appointment": appointment_output(a), "conversation": conversation_output(conversation)}


def confirm_proposal(conversation, data):
    from datalayer.booking_tools import ProposalConflict, confirm_visit_proposal

    try:
        return confirm_visit_proposal(conversation, data.proposal_id, data.confirmed)
    except AppointmentProposal.DoesNotExist:
        raise HttpError(404, "Propuesta no encontrada.")
    except ProposalConflict as exc:
        raise HttpError(409, str(exc))
