from datetime import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import SessionAuthIsStaff
from pydantic import Field

from api.auth import BrowserAuth, browser_id
from datalayer.conversations import conversation_output
from datalayer.followups import (
    FIELDS,
    due_date,
    ensure_cycle,
    output,
    policy,
    set_permission,
)
from datalayer.models import (
    Conversation,
    FollowupAttempt,
    Prospect,
    ProspectEvent,
    WhatsAppDelivery,
    WhatsAppEvent,
    WhatsAppTemplate,
)
from worker.whatsapp import WhatsAppError, configured, sync_templates

crm = Router(auth=SessionAuthIsStaff())
chat = Router(auth=BrowserAuth())


class PermissionInput(Schema):
    allowed: bool


class PolicyInput(Schema):
    send_time: time


class CycleAction(Schema):
    action: str
    conversation_id: str | None = None


class TemplateInput(Schema):
    enabled: bool
    fields: list[str] = Field(max_length=10)


@chat.put("/{conversation_id}/followup-permission", response=dict)
def website_permission(request, conversation_id: str, data: PermissionInput):
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, browser_id=browser_id(request)
    )
    if not conversation.declared_phone:
        raise HttpError(409, "Primero confirma tu celular.")
    set_permission(conversation, data.allowed)
    conversation.refresh_from_db()
    return conversation_output(conversation)


@crm.get("/followup-policy", response=dict)
def get_policy(request):
    return {"send_time": policy().send_time.isoformat(), "whatsapp_configured": configured()}


@crm.put("/followup-policy", response=dict)
def update_policy(request, data: PolicyInput):
    if data.send_time.second or data.send_time.microsecond or data.send_time.tzinfo:
        raise HttpError(422, "Usa hora y minutos de Guadalajara.")
    row = policy()
    row.send_time = data.send_time
    row.save()
    return get_policy(request)


@crm.get("/prospects/{prospect_id}/followup", response=dict)
def get_followup(request, prospect_id: int):
    return output(get_object_or_404(Prospect, pk=prospect_id))


@crm.post("/prospects/{prospect_id}/followup", response=dict)
def cycle_action(request, prospect_id: int, data: CycleAction):
    from datetime import timedelta

    from datalayer.prospects import is_paused

    with transaction.atomic():
        list(
            Conversation.objects.select_for_update().filter(prospect_id=prospect_id).order_by("pk")
        )
        prospect = get_object_or_404(Prospect.objects.select_for_update(), pk=prospect_id)
        cycle = prospect.followup_cycles.order_by("-created_at").first()
        if data.action == "new_intention":
            conversation = get_object_or_404(
                Conversation, pk=data.conversation_id, prospect=prospect
            )
            ensure_cycle(conversation, new=True, actor=request.user)
        elif not cycle:
            raise HttpError(409, "No existe un ciclo de seguimiento.")
        elif data.action == "stop":
            set_permission(cycle.conversation, False, actor=request.user)
        elif data.action == "record_permission":
            # Explicit staff attestation, not an automatic permission inferred from phone.
            set_permission(cycle.conversation, True, actor=request.user)
        elif data.action == "resume":
            if cycle.closed_at or timezone.now() >= due_date(cycle, 28) + timedelta(hours=1):
                raise HttpError(409, "El ciclo terminó; requiere una nueva intención.")
            if (
                prospect.contact_opted_out
                or is_paused(cycle.conversation)
                or prospect.status == "not_interested"
                or prospect.appointments.filter(
                    status__in=["pending", "confirmed", "review"]
                ).exists()
            ):
                raise HttpError(
                    409, "Revisa permiso, pausa, estado comercial y citas antes de reactivar."
                )
            cycle.suspended, cycle.reason = False, ""
            cycle.save(update_fields=["suspended", "reason"])
            ProspectEvent.objects.create(
                prospect=prospect,
                actor=request.user,
                description="Reactivación del seguimiento dentro del ciclo original.",
            )
        else:
            raise HttpError(422, "Acción inválida.")
    return output(prospect)


@crm.get("/whatsapp/templates", response=list[dict])
def templates(request):
    return [
        {
            "id": t.pk,
            "name": t.name,
            "language": t.language,
            "body": t.body,
            "status": t.status,
            "fields": t.fields,
            "enabled": t.enabled,
            "synced_at": t.synced_at.isoformat(),
        }
        for t in WhatsAppTemplate.objects.order_by("name")
    ]


@crm.post("/whatsapp/templates/sync", response=dict)
def sync(request):
    try:
        return {"count": sync_templates()}
    except (WhatsAppError, ValueError, KeyError):
        raise HttpError(
            409, "No pudimos consultar las plantillas. Revisa Meta y la configuración local."
        )


@crm.put("/whatsapp/templates/{template_id}", response=dict)
def update_template(request, template_id: int, data: TemplateInput):
    import re

    template = get_object_or_404(WhatsAppTemplate, pk=template_id)
    slots = re.findall(r"\{\{(.*?)\}\}", template.body)
    if data.enabled and (
        template.status != "APPROVED"
        or not data.fields
        or any(f not in FIELDS for f in data.fields)
        or slots != [str(i + 1) for i in range(len(data.fields))]
    ):
        raise HttpError(
            422,
            "Usa una plantilla aprobada con variables numeradas y datos de búsqueda permitidos.",
        )
    template.enabled, template.fields = data.enabled, data.fields
    template.save(update_fields=["enabled", "fields"])
    return {"ok": True}


@crm.get("/whatsapp/review", response=dict)
def channel_review(request):
    return {
        "events": list(
            WhatsAppEvent.objects.filter(status="review").values("id", "error_code", "received_at")
        ),
        "deliveries": [
            {
                "id": str(d.pk),
                "conversation_id": str(d.conversation_id),
                "status": d.status,
                "error_code": d.error_code,
                "created_at": d.created_at.isoformat(),
            }
            for d in WhatsAppDelivery.objects.filter(
                status__in=["blocked", "failed", "uncertain"]
            ).order_by("-created_at")[:100]
        ],
    }


@crm.post("/whatsapp/deliveries/{delivery_id}/retry", response=dict)
def retry(request, delivery_id: str):
    from worker.dispatch import enqueue_followup, enqueue_whatsapp_delivery

    with transaction.atomic():
        delivery = get_object_or_404(WhatsAppDelivery.objects.select_for_update(), pk=delivery_id)
        if delivery.status not in {"blocked", "failed"}:
            raise HttpError(409, "No se reenvían entregas inciertas, en curso o aceptadas.")
        attempt = FollowupAttempt.objects.filter(delivery=delivery).first()
        if attempt and timezone.now() >= attempt.expires_at:
            raise HttpError(409, "La ventana de ese seguimiento ya terminó.")
        delivery.status, delivery.error_code, delivery.sent_at = "queued", "", None
        delivery.save(update_fields=["status", "error_code", "sent_at", "updated_at"])
        if attempt:
            enqueue_followup(attempt.pk)
        else:
            enqueue_whatsapp_delivery(delivery.pk)
    return {"ok": True}
