from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.inventory import public_inventory, public_property
from datalayer.memory import visible_messages
from datalayer.models import Conversation, Message
from datalayer.prospects import is_paused, notice, prepare_declared_phone, record_interest


def message_output(message):
    from datalayer.public_history import message_projection

    public = message_projection(message)
    delivery = message.whatsappdelivery_set.order_by("created_at").last()
    return {
        "id": message.pk,
        "role": "assistant" if message.display_kind == "card" else message.role,
        "text": "" if message.display_kind == "card" else public["text"],
        "properties": public["properties"] if message.role == "assistant" or message.display_kind == "card" else [],
        "is_error": message.is_error,
        "delivery_status": delivery.status if delivery else None,
        "presentation": public["presentation"],
    }


@transaction.atomic
def receive_message(conversation_id, owner_browser_id, text, client_message_id, *, property_id=None):
    from worker.dispatch import enqueue_conversation

    conversation = Conversation.objects.select_for_update(no_key=True).get(
        id=conversation_id, browser_id=owner_browser_id
    )
    existing = Message.objects.filter(
        conversation=conversation, client_message_id=client_message_id
    ).first()
    if existing:
        return conversation
    prop = None
    if property_id is not None:
        prop = public_inventory().filter(pk=property_id).first()
        if prop is None:
            raise ValidationError({"property_id": "La propiedad ya no está disponible. Revisa otras opciones."})
        text = "Acción de interfaz: la persona pulsó «Me interesa» en la propiedad referenciada. El interés ya quedó registrado."
    already_shown = prop and any(
        card.get("id") == prop.pk
        for previous in visible_messages(conversation).exclude(display_kind="hidden")
        for card in previous.properties
    )
    message = Message.objects.create(
        conversation=conversation,
        role="user",
        text=text.strip(),
        kind="property_interest" if prop else "text",
        display_kind=("hidden" if already_shown else "card") if prop else "message",
        client_message_id=client_message_id,
        properties=[public_property(prop)] if prop else [],
    )
    if conversation.interest_expressed or conversation.human_requested:
        prepare_declared_phone(conversation)
    conversation.revision += 1
    conversation.pending_since = conversation.pending_since or timezone.now()
    paused = is_paused(conversation)
    if paused:
        conversation.answered_revision = conversation.revision
        conversation.pending_since = None
    conversation.save(
        update_fields=["revision", "answered_revision", "pending_since", "updated_at"]
    )
    if prop:
        result = record_interest(conversation, {"property_ids": [prop.pk]})
        if result.get("error"):
            raise ValidationError({"property_id": "La propiedad ya no está disponible. Revisa otras opciones."})
    if paused:
        notice(conversation, "paused_message", f"paused:{message.pk}", message.text[:1000])
    else:
        enqueue_conversation(conversation.pk)
    return conversation


def conversation_output(conversation):
    from datalayer.appointments import appointment_output, proposal_output
    from datalayer.models import AppointmentOperation, AppointmentProposal
    from datalayer.replies import reply_projection

    proposal = AppointmentProposal.objects.filter(conversation=conversation).first()
    if proposal and AppointmentOperation.objects.filter(request_id=proposal.pk).exists():
        proposal = None
    return {
        **reply_projection(conversation),
        "id": conversation.pk,
        "criteria": conversation.criteria,
        "processing": conversation.revision > conversation.answered_revision
        and not is_paused(conversation),
        "pending_contact": conversation.contact_candidate or None,
        "contact_registered": bool(conversation.declared_phone),
        "automation_paused": is_paused(conversation),
        "human_requested": conversation.human_requested,
        "has_interest": conversation.interest_expressed,
        "followup_permission": conversation.followup_permission,
        "visit_proposal": proposal_output(proposal) if proposal else None,
        "appointments": [
            appointment_output(a)
            for a in conversation.appointments.select_related("property", "advisor").order_by(
                "created_at"
            )
        ],
        "visits_processing": AppointmentOperation.objects.filter(
            appointment__conversation=conversation, status__in=["queued", "running", "verifying"]
        ).exists(),
        "messages": [message_output(m) for m in visible_messages(conversation).exclude(display_kind="hidden")],
    }
