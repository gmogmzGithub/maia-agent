"""Prospect capture, ownership and CRM changes. Browser identity stays on Conversation."""

import re

import phonenumbers
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from datalayer.models import (
    Advisor,
    Conversation,
    Message,
    Notification,
    Property,
    Prospect,
    ProspectEvent,
)
from datalayer.schemas import ContactInput, ContactNameInput, InterestInput


def normalize_phone(value):
    try:
        phone = phonenumbers.parse(value, "MX")
        if not phonenumbers.is_valid_number(phone):
            raise ValueError
        return phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)
    except (phonenumbers.NumberParseException, ValueError):
        raise ValidationError(
            {"phone": "Revisa el celular e incluye el código de país si no es de México."}
        )


def default_advisor():
    return Advisor.objects.filter(is_default=True).first()


def prepare_declared_phone(conversation, name=""):
    """Prepare an unambiguous phone in the current messages; only the UI can confirm it."""
    if conversation.declared_phone:
        return
    last_reply = (
        conversation.messages.filter(role="assistant")
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
        or 0
    )
    phones = set()
    for text in conversation.messages.filter(role="user", id__gt=last_reply).values_list(
        "text", flat=True
    ):
        for match in phonenumbers.PhoneNumberMatcher(text, "MX"):
            prefix = text[max(0, match.start - 45) : match.start]
            explicit = re.search(
                r"(?:cel(?:ular)?|tel(?:[eé]fono)?|whats\s?app|mi\s+n[uú]mero)\W*(?:es\W*)?$",
                prefix,
                re.IGNORECASE,
            )
            if explicit or text.strip() == match.raw_string.strip():
                phones.add(
                    phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                )
    if len(phones) == 1:
        conversation.contact_candidate = {
            "phone": phones.pop(),
            "name": name.strip() or conversation.contact_candidate.get("name", ""),
        }
        conversation.save(update_fields=["contact_candidate", "updated_at"])


def is_paused(conversation):
    return conversation.automation_paused or (
        conversation.prospect_id is not None
        and Prospect.objects.filter(pk=conversation.prospect_id, automation_paused=True).exists()
    )


@transaction.atomic
def notice(conversation, reason, key, summary=""):
    from worker.dispatch import enqueue_notification

    advisor_id = conversation.advisor_id
    if conversation.prospect_id:
        advisor_id = Prospect.objects.get(pk=conversation.prospect_id).advisor_id
    notification, created = Notification.objects.get_or_create(
        event_key=key,
        defaults={
            "conversation": conversation,
            "reason": reason,
            "summary": summary[:1000],
            "advisor_id": advisor_id,
        },
    )
    if created:
        if conversation.prospect_id:
            from django.utils import timezone

            Prospect.objects.filter(pk=conversation.prospect_id).update(updated_at=timezone.now())
        enqueue_notification(notification.pk)
    return notification


def record_name(conversation, arguments):
    """Remember a volunteered name without starting an intention or changing permission."""
    name = ContactNameInput.model_validate(arguments).name.strip()
    if not name:
        return {"error": "name_required"}
    conversation.contact_name = name
    if conversation.contact_candidate:
        conversation.contact_candidate = {**conversation.contact_candidate, "name": name}
    conversation.save(update_fields=["contact_name", "contact_candidate", "updated_at"])
    # A declared website phone does not authorize edits to the shared CRM identity.
    if conversation.channel == "whatsapp" and conversation.prospect_id:
        Prospect.objects.filter(pk=conversation.prospect_id).update(
            name=name, updated_at=timezone.now()
        )
    return {"recorded": True, "name": name}


@transaction.atomic
def record_interest(conversation, arguments):
    data = InterestInput.model_validate(arguments)
    if data.name.strip():
        record_name(conversation, {"name": data.name})
    already_requested = conversation.human_requested
    properties = {
        p.pk: p for p in Property.objects.filter(pk__in=data.property_ids, published=True)
    }
    if len(properties) != len(set(data.property_ids)):
        return {"error": "property_not_available"}
    old_ids = set(conversation.interests.values_list("pk", flat=True))
    conversation.interest_expressed = True
    new_ids = set(properties) - old_ids
    if not conversation.advisor_id and not old_ids:
        first = properties.get(data.property_ids[0]) if data.property_ids else None
        conversation.advisor = first.advisor if first and first.advisor_id else default_advisor()
    conversation.interests.add(*new_ids)
    if data.human_requested:
        conversation.human_requested = True
    conversation.save(
        update_fields=["advisor", "human_requested", "interest_expressed", "updated_at"]
    )
    prepare_declared_phone(conversation, data.name or conversation.contact_name)
    from datalayer.followups import mark_intent

    mark_intent(conversation)
    if conversation.prospect_id:
        prospect = Prospect.objects.select_for_update().get(pk=conversation.prospect_id)
        prospect.properties.add(*new_ids)
        if new_ids:
            notice(
                conversation,
                "new_interest",
                f"interest:{conversation.pk}:{conversation.revision}",
                data.summary,
            )
    if data.human_requested and not already_requested:
        notice(
            conversation,
            "human_request",
            f"human:{conversation.pk}:{conversation.revision}",
            data.summary,
        )
    return {
        "recorded": True,
        "contact_registered": bool(conversation.declared_phone),
        "human_request_recorded": data.human_requested,
        "pending_confirmation": bool(conversation.contact_candidate),
        "detail": "Solicitud registrada en el CRM. El envío de Telegram tiene su propio estado; no afirmes que fue entregado.",
    }


def prepare_contact(conversation, arguments):
    data = ContactInput.model_validate(arguments)
    phone = normalize_phone(data.phone)
    if conversation.declared_phone and conversation.declared_phone != phone:
        return {
            "error": "contact_already_registered",
            "detail": "Pide al asesor corregir el número registrado.",
        }
    if conversation.declared_phone:
        return {
            "contact_registered": True,
            "detail": "El contacto ya está registrado en esta conversación. Continúa sin pedir otra confirmación.",
        }
    if not conversation.interest_expressed and not conversation.human_requested:
        return {
            "error": "interest_required",
            "detail": "Registra primero el interés o la solicitud humana expresada.",
        }
    conversation.contact_candidate = {
        "phone": phone,
        "name": data.name.strip() or conversation.contact_name,
    }
    conversation.save(update_fields=["contact_candidate", "updated_at"])
    return {
        "pending_confirmation": True,
        "phone": phone,
        "detail": "El website muestra el número para que la persona lo confirme. No hay registro de prospecto hasta ese clic; no se envía SMS.",
    }


@transaction.atomic
def confirm_contact(conversation_id, owner_browser_id, data):
    from worker.dispatch import enqueue_conversation

    conversation = Conversation.objects.select_for_update().get(
        pk=conversation_id, browser_id=owner_browser_id
    )
    phone = normalize_phone(data.phone)
    if conversation.declared_phone == phone:
        return conversation
    if conversation.declared_phone:
        raise ValidationError({"phone": "El asesor debe corregir el número ya registrado."})
    if phone != conversation.contact_candidate.get("phone"):
        raise ValidationError({"phone": "Confirma el número que aparece en la conversación."})
    prospect, created = Prospect.objects.get_or_create(
        phone=phone,
        defaults={
            "name": data.name.strip(),
            "advisor": conversation.advisor or default_advisor(),
            "criteria": conversation.criteria,
            "criteria_source": conversation,
            "next_step": "Contactar al prospecto y confirmar el siguiente paso.",
        },
    )
    prospect = Prospect.objects.select_for_update().get(pk=prospect.pk)
    conversation.prospect = prospect
    conversation.declared_phone = phone
    conversation.contact_name = data.name.strip()
    conversation.contact_candidate = {}
    conversation.followup_permission = getattr(data, "whatsapp_followup", False)
    conversation.save(
        update_fields=[
            "prospect",
            "declared_phone",
            "contact_name",
            "contact_candidate",
            "followup_permission",
            "updated_at",
        ]
    )
    prospect.properties.add(*conversation.interests.all())
    from datalayer.followups import ensure_cycle

    ensure_cycle(conversation)
    ProspectEvent.objects.create(
        prospect=prospect,
        description="Nueva conversación asociada por celular declarado; identidad sin verificar.",
    )
    notice(
        conversation,
        "new_prospect" if created else "new_interest",
        f"contact:{conversation.pk}",
        "Contacto confirmado en el website. Identidad sin verificar.",
    )
    Message.objects.create(
        conversation=conversation,
        role="user",
        text="Confirmo que mi celular es "
        + phone
        + (f". Mi nombre es {data.name.strip()}." if data.name.strip() else "."),
    )
    conversation.revision += 1
    if is_paused(conversation):
        conversation.answered_revision = conversation.revision
        conversation.pending_since = None
    else:
        from django.utils import timezone

        conversation.pending_since = timezone.now()
    conversation.save(
        update_fields=["revision", "answered_revision", "pending_since", "updated_at"]
    )
    if not is_paused(conversation):
        enqueue_conversation(conversation.pk)
    return conversation


@transaction.atomic
def save_advisor(data, advisor=None):
    # Serialize changes to the default without adding a configuration service.
    list(Advisor.objects.select_for_update().order_by("pk"))
    if data.is_default:
        Advisor.objects.filter(is_default=True).update(is_default=False)
    advisor = advisor or Advisor()
    for key, value in data.model_dump().items():
        setattr(advisor, key, value.strip() if isinstance(value, str) else value)
    advisor.full_clean()
    advisor.save()
    return advisor


@transaction.atomic
def update_prospect(prospect_id, data, actor):
    list(Conversation.objects.select_for_update().filter(prospect_id=prospect_id).order_by("pk"))
    prospect = Prospect.objects.select_for_update().get(pk=prospect_id)
    if data.advisor_id and not Advisor.objects.filter(pk=data.advisor_id).exists():
        raise ValidationError({"advisor_id": "Selecciona un asesor existente."})
    changes = []
    for field in ["name", "advisor_id", "status", "next_step", "automation_paused"]:
        value = getattr(data, field)
        if getattr(prospect, field) != value:
            changes.append(field)
        setattr(prospect, field, value)
    criteria = data.criteria.model_dump(mode="json")
    from datalayer.schemas import SearchCriteria

    if SearchCriteria.model_validate(prospect.criteria).model_dump(mode="json") != criteria:
        changes.append("criteria")
        prospect.criteria_source = None
    prospect.criteria = criteria
    prospect.save()
    from django.utils import timezone

    from datalayer.models import FollowupCycle

    if data.status == "not_interested":
        FollowupCycle.objects.filter(prospect=prospect, closed_at__isnull=True).update(
            closed_at=timezone.now(), reason="not_interested"
        )
    elif data.status == "scheduled":
        FollowupCycle.objects.filter(prospect=prospect, closed_at__isnull=True).update(
            suspended=True, reason="appointment"
        )
    if "automation_paused" in changes:
        # Invalidate all running/queued turns; a phone match never grants history access.
        Conversation.objects.filter(prospect=prospect).update(
            revision=F("revision") + 1,
            answered_revision=F("revision") + 1,
            pending_since=None,
            automation_paused=False,
        )
    if "status" in changes and data.status == "attending":
        Conversation.objects.filter(prospect=prospect).update(human_requested=False)
    if changes:
        labels = {
            "name": "nombre",
            "advisor_id": "asesor",
            "status": "estado comercial",
            "next_step": "siguiente paso",
            "automation_paused": "pausa de Maia",
            "criteria": "requisitos",
        }
        ProspectEvent.objects.create(
            prospect=prospect,
            actor=actor,
            description="Actualización desde CRM: " + ", ".join(labels[c] for c in changes),
        )
    return prospect
