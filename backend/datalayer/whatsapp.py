"""Authenticated channel events, deduplication and persisted outgoing messages."""

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.models import (
    AppointmentProposal,
    Conversation,
    Message,
    Prospect,
    WhatsAppDelivery,
    WhatsAppEvent,
)
from datalayer.prospects import default_advisor, is_paused, normalize_phone
from datalayer.whatsapp_presentation import structured_payload


def canonical_number(value):
    """Remove Mexico's legacy mobile marker without changing the stored channel ID."""
    return "52" + value[3:] if value.startswith("521") and len(value) == 13 else value


def store_events(payload):
    from worker.dispatch import enqueue_whatsapp_event

    with transaction.atomic():
        for entry in payload.get("entry", []):
            if str(entry.get("id")) != settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
                continue
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if (
                    change.get("field") != "messages"
                    or str(value.get("metadata", {}).get("phone_number_id"))
                    != settings.WHATSAPP_PHONE_NUMBER_ID
                ):
                    continue
                for kind in ("messages", "statuses"):
                    for item in value.get(kind, []):
                        if (
                            not isinstance(item, dict)
                            or not isinstance(item.get("id"), str)
                            or len(item["id"]) > 256
                        ):
                            continue
                        key = (
                            "in:" + item["id"]
                            if kind == "messages"
                            else "status:"
                            + hashlib.sha256(
                                (
                                    item["id"]
                                    + ":"
                                    + str(item.get("status"))
                                    + ":"
                                    + str(item.get("timestamp"))
                                ).encode()
                            ).hexdigest()
                        )
                        event, created = WhatsAppEvent.objects.get_or_create(
                            key=key, defaults={"payload": {"kind": kind, "data": item}}
                        )
                        if created:
                            enqueue_whatsapp_event(event.pk)


def queue_reply(conversation, message, *, key=None, proposal=None):
    from datalayer.public_history import message_projection

    public = message_projection(message)
    if message.presentation is not None:
        payload = structured_payload(conversation, public["presentation"], public["properties"])
        return _queue_payload(conversation, message, payload, key)
    text = public["text"]
    if public["properties"]:
        from harness.presentation.properties import property_text, split_closing_question

        intro, question = split_closing_question(text)
        cards = "\n\n".join(
            property_text(p, conversation.criteria, settings.PUBLIC_BASE_URL)
            for p in public["properties"][:3]
        )
        text = "\n\n".join(part for part in (intro, cards, question) if part)
    from datalayer.models import AppointmentOperation

    if proposal and proposal.conversation_id != conversation.pk:
        raise ValueError("proposal belongs to another conversation")
    if proposal and AppointmentOperation.objects.filter(request_id=proposal.pk).exists():
        proposal = None
    if proposal:
        from datalayer.appointments import visit_time

        action = {
            "create": "Confirmar visita",
            "move": "Reprogramar visita",
            "cancel": "Cancelar visita",
        }[proposal.action]
        summary = f"Tu visita a {proposal.property.title}\n{visit_time(proposal.start, proposal.end)}, hora de Guadalajara.\nCon {proposal.advisor.name} · {int((proposal.end - proposal.start).total_seconds() // 60)} minutos."
        payload = {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": (summary + "\n\n" + text)[:1024]},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "visit:" + str(proposal.pk), "title": action},
                        }
                    ]
                },
            },
        }
    else:
        payload = {"type": "text", "text": {"body": text[:4096], "preview_url": False}}
    return _queue_payload(conversation, message, payload, key)


def _queue_payload(conversation, message, payload, key):
    from worker.dispatch import enqueue_whatsapp_delivery

    delivery, created = WhatsAppDelivery.objects.get_or_create(
        event_key=key or f"reply:{message.pk}",
        defaults={
            "conversation": conversation,
            "message": message,
            "recipient": conversation.whatsapp_sender,
            "payload": payload,
            "revision": conversation.revision,
        },
    )
    if created:
        enqueue_whatsapp_delivery(delivery.pk)
    return delivery


def reply(conversation, text, key):
    msg = Message.objects.create(conversation=conversation, role="assistant", text=text)
    return queue_reply(conversation, msg, key=key)


def apply_status(item):
    status = item.get("status")
    rank = {"sent": 1, "delivered": 2, "read": 3}
    query = WhatsAppDelivery.objects.select_for_update().filter(provider_id=item["id"])
    delivery = query.first()
    if not delivery:
        try:
            delivery = (
                WhatsAppDelivery.objects.select_for_update()
                .filter(pk=uuid.UUID(item.get("biz_opaque_callback_data", "")))
                .first()
            )
        except (ValueError, TypeError, AttributeError):
            return
    if not delivery or (
        item.get("recipient_id")
        and canonical_number(str(item["recipient_id"])) != canonical_number(delivery.recipient)
    ):
        return
    if delivery.provider_id and delivery.provider_id != item["id"]:
        return
    if (
        status in rank
        and rank[status] > rank.get(delivery.status, 0)
        or status == "failed"
        and delivery.status not in {"delivered", "read"}
    ):
        delivery.status = status
        delivery.provider_id = item["id"]
        delivery.error_code = "meta_delivery_failed" if status == "failed" else ""
        delivery.save()
        from datalayer.models import FollowupAttempt

        FollowupAttempt.objects.filter(delivery=delivery).update(
            status=delivery.status, reason=delivery.error_code, updated_at=timezone.now()
        )


def process_event(event_id):
    from datalayer.booking_tools import confirm_visit_proposal
    from datalayer.conversations import receive_message
    from datalayer.followups import mark_intent, set_permission

    try:
        with transaction.atomic():
            event = WhatsAppEvent.objects.select_for_update().get(pk=event_id)
            if event.status != "queued":
                return
            item = event.payload["data"]
            if event.payload["kind"] == "statuses":
                apply_status(item)
            else:
                sender = str(item.get("from", ""))
                if not re.fullmatch(r"[0-9]{7,20}", sender):
                    raise ValueError("invalid_sender")
                stamp = datetime.fromtimestamp(int(item["timestamp"]), dt_timezone.utc)
                if stamp > timezone.now() + timedelta(minutes=5):
                    raise ValueError("invalid_timestamp")
                # Meta can retain Mexico's legacy mobile prefix in the channel ID.
                # Match the CRM's E.164 phone without changing the reply address.
                phone = normalize_phone("+" + canonical_number(sender))
                conversation, created = Conversation.objects.get_or_create(
                    whatsapp_sender=sender, defaults={"channel": "whatsapp", "browser_id": None}
                )
                conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
                if created:
                    prospect, prospect_created = Prospect.objects.get_or_create(
                        phone=phone, defaults={"advisor": default_advisor()}
                    )
                    conversation.prospect, conversation.declared_phone = prospect, phone
                    conversation.followup_permission = not prospect.contact_opted_out
                    # A verified recipient can resume the source of their own follow-up.
                    prior = (
                        WhatsAppDelivery.objects.filter(
                            recipient=sender,
                            status__in=["sent", "delivered", "read"],
                            followupattempt__isnull=False,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    if prior and prior.conversation.prospect_id == prospect.pk:
                        conversation.context_origin = prior.conversation
                        conversation.criteria = prospect.criteria
                    conversation.save()
                    if prospect_created:
                        prospect.criteria_source = conversation
                        prospect.save(update_fields=["criteria_source", "updated_at"])
                    elif (
                        prior
                        and prior.conversation.prospect_id == prospect.pk
                        and prospect.criteria_source_id == prior.conversation_id
                    ):
                        prospect.criteria_source = conversation
                        prospect.save(update_fields=["criteria_source", "updated_at"])
                if not conversation.last_whatsapp_at or stamp > conversation.last_whatsapp_at:
                    conversation.last_whatsapp_at = stamp
                    conversation.save(update_fields=["last_whatsapp_at"])
                event.conversation = conversation
                kind = item.get("type")
                text = str(item.get("text", {}).get("body", ""))[:4000] if kind == "text" else ""
                button = (
                    item.get("interactive", {}).get("button_reply", {}).get("id", "")
                    if kind == "interactive"
                    else ""
                )
                clean = re.sub(r"[.!¡¿?\s]+", " ", text.lower()).strip()
                opted_out = clean in {
                    "baja",
                    "stop",
                    "cancelar seguimiento",
                    "no me escribas",
                    "no me escriban",
                    "no quiero recibir mensajes",
                    "no quiero recibir más mensajes",
                    "no quiero recibir mas mensajes",
                    "no quiero más mensajes",
                    "no quiero mas mensajes",
                }
                if opted_out:
                    Message.objects.create(conversation=conversation, role="user", text=text)
                    set_permission(conversation, False)
                    reply(
                        conversation,
                        "Claro, no te enviaré más seguimientos. Si quieres retomar tu búsqueda, escríbeme cuando quieras.",
                        f"optout:{event.pk}",
                    )
                elif button.startswith("visit:"):
                    Message.objects.create(
                        conversation=conversation,
                        role="user",
                        text="Confirmo la propuesta de visita con el botón de WhatsApp.",
                    )
                    try:
                        proposal_id = uuid.UUID(button[6:])
                        proposal = AppointmentProposal.objects.get(
                            pk=proposal_id, conversation=conversation
                        )
                        confirm_visit_proposal(conversation, proposal_id)
                        progress = {
                            "create": "Estoy agendando tu visita. Enseguida te confirmo.",
                            "move": "Estoy cambiando el horario de tu visita. Enseguida te confirmo.",
                            "cancel": "Estoy cancelando tu visita. Enseguida te confirmo.",
                        }[proposal.action]
                        reply(
                            conversation,
                            progress,
                            f"visit-click:{event.pk}",
                        )
                    except Exception:
                        reply(
                            conversation,
                            "Ese botón ya no está disponible. ¿Quieres que revisemos los horarios otra vez?",
                            f"visit-error:{event.pk}",
                        )
                elif text.strip():
                    receive_message(
                        conversation.pk, None, text, uuid.uuid5(uuid.NAMESPACE_URL, event.key)
                    )
                    Message.objects.filter(
                        conversation=conversation,
                        client_message_id=uuid.uuid5(uuid.NAMESPACE_URL, event.key),
                    ).update(created_at=stamp)
                    conversation.refresh_from_db()
                    if item.get("referral") and not conversation.intent_started_at:
                        conversation.intent_started_at = stamp
                        conversation.save(update_fields=["intent_started_at"])
                        mark_intent(conversation)
                elif not is_paused(conversation):
                    Message.objects.create(
                        conversation=conversation,
                        role="user",
                        text="[Audio recibido; sin transcripción]"
                        if kind == "audio"
                        else "[Mensaje no textual recibido]",
                    )
                    reply(
                        conversation,
                        "Por ahora puedo ayudarte por texto. ¿Puedes escribir tu mensaje?",
                        f"unsupported:{event.pk}",
                    )
                event.processed_at, event.status = timezone.now(), "processed"
            event.processed_at, event.status = timezone.now(), "processed"
            event.save(update_fields=["conversation", "processed_at", "status"])
    except Exception as exc:
        # Keep a reviewable failure without logging personal payload or provider secrets.
        WhatsAppEvent.objects.filter(pk=event_id, status="queued").update(
            status="review", error_code=type(exc).__name__
        )
