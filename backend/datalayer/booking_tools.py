
"""Conversation-owned booking tools. They prepare actions, never confirm for the user."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from datalayer.appointments import (
    booking_policy,
    connection_for,
    date_time,
    pending_request,
    proposal_output,
    slots,
    validate_slot,
    visit_advisor,
)
from datalayer.inventory import public_inventory
from datalayer.models import (
    Appointment,
    AppointmentOperation,
    AppointmentProposal,
    Conversation,
)
from datalayer.prospects import is_paused


class ProposalConflict(Exception):
    pass


def pending_visit_proposal(conversation_id):
    return (
        AppointmentProposal.objects.select_related("property", "advisor")
        .filter(
            conversation_id=conversation_id,
            created_at__gt=timezone.now() - timedelta(minutes=10),
        )
        .exclude(pk__in=AppointmentOperation.objects.values("request_id"))
        .first()
    )


def confirm_visit_proposal(conversation, proposal_id, confirmed=True):
    from django.utils import timezone

    from datalayer.appointments import submit

    with transaction.atomic():
        booking_policy(lock=True)
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        proposal = AppointmentProposal.objects.select_for_update().get(
            conversation=conversation, pk=proposal_id
        )
        if is_paused(conversation):
            raise ProposalConflict("El asesor tiene el control de esta conversación.")
        if not confirmed or proposal.created_at < timezone.now() - timedelta(minutes=10):
            raise ProposalConflict("Consulta nuevamente el horario y confirma la cita.")
        return submit(
            conversation,
            proposal.property,
            proposal.start,
            request_id=proposal.pk,
            action=proposal.action,
            appointment=proposal.appointment,
            expected_end=proposal.end,
            expected_advisor=proposal.advisor_id,
        )


def visit_tool(conversation_id, revision, name, arguments):
    from datalayer.errors import Superseded

    conversation = Conversation.objects.get(pk=conversation_id)
    if conversation.revision != revision or is_paused(conversation):
        raise Superseded
    if name == "request_visit_help":
        summary = str(arguments.get("summary", "Solicitud de visita pendiente"))[:1000]
        return pending_request(conversation, summary)
    if name == "visit_slots":
        appointment = None
        if arguments.get("appointment_id"):
            appointment = Appointment.objects.get(
                pk=arguments["appointment_id"], conversation=conversation
            )
        return slots(
            conversation,
            int(arguments["property_id"]),
            arguments.get("day") or None,
            appointment=appointment,
            offset=max(0, min(int(arguments.get("offset", 0)), 100)),
        )
    if name != "prepare_visit":
        return {"error": "unknown_tool"}
    if not conversation.declared_phone or not conversation.prospect_id:
        return {
            "error": "contact_required",
            "detail": "Pide confirmar su celular con el formulario antes de reservar.",
        }
    action = arguments.get("action", "create")
    if action not in {"create", "move", "cancel"}:
        return {"error": "invalid_action"}
    appointment = None
    if action != "create":
        appointment = Appointment.objects.get(
            pk=arguments.get("appointment_id"), conversation=conversation, status="confirmed"
        )
        prop, advisor = appointment.property, appointment.advisor
    else:
        prop = public_inventory().get(pk=int(arguments["property_id"]))
        advisor = visit_advisor(prop)
    if not advisor:
        return pending_request(conversation, "Visita pendiente: falta configurar asesor.")
    start = appointment.start if action == "cancel" else date_time(arguments["start"])
    end = start + timedelta(minutes=appointment.duration if appointment else prop.visit_duration)
    if action != "cancel":
        connection_for(advisor)
        validate_slot(
            prop,
            start,
            end,
            booking_policy(),
            duration=appointment.duration if appointment else None,
        )
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
        if conversation.revision != revision or is_paused(conversation):
            raise Superseded
        proposal, _ = AppointmentProposal.objects.update_or_create(
            conversation=conversation,
            defaults={
                "property": prop,
                "advisor": advisor,
                "appointment": appointment,
                "action": action,
                "start": start,
                "end": end,
            },
        )
        # A different proposal gets a different request key; old confirmations fail.
        import uuid

        old_id = proposal.pk
        AppointmentProposal.objects.filter(pk=old_id).update(id=uuid.uuid4())
        proposal = AppointmentProposal.objects.get(conversation=conversation)
    return {
        "proposal": proposal_output(proposal),
        "detail": "El canal muestra un resumen y botón de confirmación. El prospecto debe pulsarlo; todavía no hay cita creada ni modificada.",
    }
