"""Explicit, bounded hourly pilot on an authenticated WhatsApp conversation."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.followups import DAYS, PILOT_TEMPLATES, end_date, template_options
from datalayer.models import Conversation, FollowupCycle, Prospect, ProspectEvent
from datalayer.prospects import is_paused
from datalayer.whatsapp import canonical_number


@transaction.atomic
def start_pilot(phone):
    prospect = Prospect.objects.select_for_update().get(phone=phone)
    conversation = Conversation.objects.select_for_update().get(
        prospect=prospect, channel="whatsapp"
    )
    if canonical_number(conversation.whatsapp_sender) != phone.lstrip("+"):
        raise ValidationError("El remitente WhatsApp no corresponde al número autorizado.")
    active = prospect.followup_cycles.filter(closed_at__isnull=True).first()
    if active:
        if active.pilot and active.pilot.get("recipient") == phone:
            return active, False
        raise ValidationError("Ya existe un ciclo abierto; no se sustituye automáticamente.")
    if is_paused(conversation) or prospect.status == "not_interested":
        raise ValidationError("Resuelve la pausa o el estado comercial antes de iniciar.")
    now = timezone.now()
    if prospect.appointments.filter(
        status__in=["pending", "confirmed", "review"], end__gt=now
    ).exists():
        raise ValidationError("Hay una cita vigente; no se modifica para forzar la prueba.")
    cycle = FollowupCycle(
        prospect=prospect,
        conversation=conversation,
        started_at=now,
        permission=True,
        pilot={
            "version": 1,
            "recipient": phone,
            "restore_opted_out": prospect.contact_opted_out,
        },
    )
    # This new, explicitly authorized test intention uses the WhatsApp search.
    prospect.criteria = conversation.criteria
    if {option["name"] for option in template_options(cycle)} != set(PILOT_TEMPLATES):
        raise ValidationError("Faltan las tres plantillas aprobadas o datos para sus variables.")
    prospect.contact_opted_out = False
    prospect.criteria_source = conversation
    prospect.save(update_fields=["contact_opted_out", "criteria", "criteria_source", "updated_at"])
    conversation.followup_permission = True
    conversation.save(update_fields=["followup_permission", "updated_at"])
    cycle.save()
    ProspectEvent.objects.create(
        prospect=prospect,
        description=(
            "PRUEBA: permiso explícito de Guillermo para ocho seguimientos cada 30 minutos. "
            "Primeros tres: operación, municipio, tipo/municipio; después selección contextual. "
            "Silencio mínimo de cinco minutos. No modifica citas ni el calendario normal. "
            "Al terminar se retira el permiso temporal."
        ),
    )
    assert end_date(cycle) > now and len(DAYS) == 8
    return cycle, True
