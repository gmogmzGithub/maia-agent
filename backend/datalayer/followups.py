"""Deterministic follow-up policy, context snapshots and durable daily attempts."""

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.models import (
    Appointment,
    Conversation,
    FollowupAttempt,
    FollowupCycle,
    FollowupPolicy,
    Message,
    Prospect,
    ProspectEvent,
    WhatsAppEvent,
    WhatsAppTemplate,
)
from datalayer.prospects import is_paused

LOCAL = ZoneInfo("America/Mexico_City")
DAYS = (1, 5, 7, 14, 18, 22, 26, 28)
FIELDS = {
    "operation",
    "kind",
    "municipality",
    "neighborhood",
    "bedrooms",
    "bathrooms",
    "parking",
    "furnished",
    "accepts_pets",
    "near_schools",
}


def policy():
    row, created = FollowupPolicy.objects.get_or_create(pk=1)
    if created:
        row.refresh_from_db()
    return row


def due_date(cycle, day):
    return datetime.combine(
        cycle.started_at.astimezone(LOCAL).date() + timedelta(days=day),
        policy().send_time,
        tzinfo=LOCAL,
    )


def mark_intent(conversation):
    if not conversation.intent_started_at:
        # The triggering customer message precedes model execution and contact capture.
        latest = conversation.messages.filter(role="user").last()
        conversation.intent_started_at = latest.created_at if latest else timezone.now()
        conversation.save(update_fields=["intent_started_at", "updated_at"])
    if conversation.prospect_id:
        ensure_cycle(conversation)


@transaction.atomic
def ensure_cycle(conversation, *, new=False, actor=None):
    if not conversation.prospect_id:
        return None
    if not conversation.intent_started_at:
        if not new:
            return None
        latest_message = conversation.messages.filter(role="user").last()
        if not latest_message:
            raise ValidationError(
                {"followup": "Primero debe existir una interacción del prospecto."}
            )
        conversation.intent_started_at = latest_message.created_at
        conversation.save(update_fields=["intent_started_at", "updated_at"])
    prospect = Prospect.objects.select_for_update().get(pk=conversation.prospect_id)
    latest = prospect.followup_cycles.order_by("-created_at").first()
    if latest and not new:
        return latest
    now = timezone.now()
    if new:
        if latest and not latest.closed_at and now <= due_date(latest, 28) + timedelta(hours=1):
            raise ValidationError({"followup": "El ciclo anterior todavía no termina."})
        boundary = (
            latest.closed_at or due_date(latest, 28) + timedelta(hours=1)
            if latest
            else conversation.created_at
        )
        interaction = conversation.messages.filter(role="user", created_at__gt=boundary).last()
        if not interaction:
            raise ValidationError(
                {"followup": "Primero debe existir una nueva interacción del prospecto."}
            )
        if latest and not latest.closed_at:
            latest.closed_at = now
            latest.reason = "completed"
            latest.save(update_fields=["closed_at", "reason"])
        started = interaction.created_at
    else:
        started = conversation.intent_started_at
    cycle = FollowupCycle.objects.create(
        prospect=prospect,
        conversation=conversation,
        started_at=started,
        permission=conversation.followup_permission is True and not prospect.contact_opted_out,
    )
    ProspectEvent.objects.create(
        prospect=prospect, actor=actor, description="Nuevo ciclo de seguimiento de 28 días."
    )
    return cycle


@transaction.atomic
def set_permission(conversation, allowed, *, actor=None):
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    conversation.followup_permission = allowed
    conversation.save(update_fields=["followup_permission", "updated_at"])
    if not conversation.prospect_id:
        return
    prospect = Prospect.objects.select_for_update().get(pk=conversation.prospect_id)
    cycle = ensure_cycle(conversation)
    # A browser cannot overwrite another conversation's consent or history.
    owns_cycle = cycle and cycle.conversation_id == conversation.pk
    if actor is not None or conversation.channel == "whatsapp" or owns_cycle:
        prospect.contact_opted_out = not allowed
        prospect.save(update_fields=["contact_opted_out", "updated_at"])
        if not allowed:
            prospect.followup_cycles.filter(closed_at__isnull=True).update(
                permission=False, closed_at=timezone.now(), reason="opted_out"
            )
        elif cycle and not cycle.closed_at:
            cycle.permission = True
            cycle.save(update_fields=["permission"])
        ProspectEvent.objects.create(
            prospect=prospect,
            actor=actor,
            description="Permiso de seguimiento por WhatsApp: "
            + ("aceptado." if allowed else "rechazado."),
        )


def eligible(cycle, now):
    prospect, conversation = cycle.prospect, cycle.conversation
    if cycle.closed_at:
        return "closed"
    if prospect.contact_opted_out or prospect.status == "not_interested":
        cycle.closed_at, cycle.reason = (
            now,
            "opted_out" if prospect.contact_opted_out else "not_interested",
        )
        cycle.save(update_fields=["closed_at", "reason"])
        return cycle.reason
    if (
        Appointment.objects.filter(
            prospect=prospect, status__in=["pending", "confirmed", "review"]
        ).exists()
        or prospect.status == "scheduled"
    ):
        cycle.suspended, cycle.reason = True, "appointment"
        cycle.save(update_fields=["suspended", "reason"])
    if cycle.suspended:
        return cycle.reason or "suspended"
    if is_paused(conversation):
        return "paused"
    if not cycle.permission:
        return "permission_required"
    if WhatsAppEvent.objects.filter(
        status="queued", payload__kind="messages", payload__data__from=prospect.phone.lstrip("+")
    ).exists():
        return "incoming_pending"
    if Message.objects.filter(
        conversation__prospect=prospect, role="user", created_at__gt=now - timedelta(hours=24)
    ).exists():
        return "recent_activity"
    return ""


def snapshot(cycle):
    prospect = cycle.prospect
    state = {
        "criteria": prospect.criteria,
        "status": prospect.status,
        "paused": prospect.automation_paused,
        "opted_out": prospect.contact_opted_out,
        "next_step": prospect.next_step,
        "conversations": list(
            prospect.conversations.order_by("pk").values_list("pk", "revision", "automation_paused")
        ),
        "appointments": list(
            prospect.appointments.order_by("pk").values_list("pk", "status", "start", "end")
        ),
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def template_options(cycle):
    criteria = cycle.prospect.criteria
    mapping = {
        "rent": "rentar",
        "sale": "comprar",
        "house": "casa",
        "apartment": "departamento",
        "land": "terreno",
    }
    options = []
    import re

    for template in WhatsAppTemplate.objects.filter(enabled=True, status="APPROVED"):
        # Only simple BODY text with numeric placeholders is supported in the pilot.
        slots = re.findall(r"\{\{(.*?)\}\}", template.body)
        if slots != [str(i + 1) for i in range(len(template.fields))] or not template.fields:
            continue
        if any(
            f not in FIELDS or criteria.get(f) is None or criteria.get(f) == ""
            for f in template.fields
        ):
            continue
        values = [
            mapping.get(str(criteria[f]), str(criteria[f]))
            if not isinstance(criteria[f], bool)
            else ("sí" if criteria[f] else "no")
            for f in template.fields
        ]
        text = template.body
        for i, value in enumerate(values, 1):
            text = text.replace("{{" + str(i) + "}}", value)
        if len(text.split()) > 45 or "\u2014" in text or text.count("?") > 1:
            continue
        options.append(
            {
                "id": template.pk,
                "name": template.name,
                "language": template.language,
                "text": text,
                "values": values,
                "body": template.body,
                "fields": template.fields,
            }
        )
    return options


def context(cycle):
    from django.db.models import Q

    # Source plus an authenticated reply to its follow-up, never all history by phone.
    sources = Conversation.objects.filter(
        Q(pk=cycle.conversation_id)
        | Q(
            channel="whatsapp",
            context_origin_id=cycle.conversation_id,
            prospect_id=cycle.prospect_id,
        )
    )
    messages = Message.objects.filter(
        conversation__in=sources, is_error=False, created_at__gte=cycle.started_at
    ).exclude(
        whatsappdelivery__status__in=[
            "queued",
            "sending",
            "blocked",
            "failed",
            "uncertain",
            "skipped",
        ]
    )
    return {
        "criteria": cycle.prospect.criteria,
        "next_step": cycle.prospect.next_step,
        "history": list(messages.order_by("created_at", "pk").values("role", "text")),
    }


@transaction.atomic
def maintain():
    from worker.dispatch import enqueue_followup

    now = timezone.now()
    for cycle in FollowupCycle.objects.select_related("prospect", "conversation").filter(
        closed_at__isnull=True
    ):
        for day in DAYS:
            due = due_date(cycle, day)
            if now < due:
                continue
            attempt, created = FollowupAttempt.objects.get_or_create(
                cycle=cycle,
                day=day,
                defaults={"due_at": due, "expires_at": due + timedelta(hours=1)},
            )
            if created or attempt.status == "queued":
                reason = "expired" if now >= attempt.expires_at else eligible(cycle, now)
                if reason:
                    attempt.status, attempt.reason = "skipped", reason
                    attempt.save(update_fields=["status", "reason", "updated_at"])
                else:
                    enqueue_followup(attempt.pk)
        if now >= due_date(cycle, 28) + timedelta(hours=1):
            cycle.closed_at, cycle.reason = now, "completed"
            cycle.save(update_fields=["closed_at", "reason"])
    # Queued work is durable; crashed generation is not automatically redrafted.
    FollowupAttempt.objects.filter(
        status="preparing", updated_at__lt=now - timedelta(minutes=3)
    ).update(status="review", reason="generation_interrupted")


def output(prospect):
    cycle = prospect.followup_cycles.order_by("-created_at").first()
    if not cycle:
        return {"cycle": None, "opted_out": prospect.contact_opted_out, "attempts": []}
    now = timezone.now()
    next_due = next((due_date(cycle, d) for d in DAYS if due_date(cycle, d) > now), None)
    return {
        "cycle": {
            "id": cycle.pk,
            "conversation_id": str(cycle.conversation_id),
            "started_at": cycle.started_at.isoformat(),
            "ends_at": (due_date(cycle, 28) + timedelta(hours=1)).isoformat(),
            "closed_at": cycle.closed_at.isoformat() if cycle.closed_at else None,
            "suspended": cycle.suspended,
            "permission": cycle.permission,
            "reason": cycle.reason,
            "next_at": next_due.isoformat() if next_due and not cycle.closed_at else None,
        },
        "opted_out": prospect.contact_opted_out,
        "attempts": [
            {
                "id": a.pk,
                "day": a.day,
                "status": a.status,
                "reason": a.reason,
                "due_at": a.due_at.isoformat(),
                "delivery_status": a.delivery.status if a.delivery_id else None,
            }
            for a in cycle.attempts.select_related("delivery").order_by("day")
        ],
    }
