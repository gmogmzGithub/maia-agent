"""Explicit, bounded pilot on an authenticated WhatsApp conversation."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.followups import (
    DAYS,
    PILOT_TEMPLATES,
    cycle_days,
    due_date,
    end_date,
    template_options,
)
from datalayer.models import Conversation, FollowupCycle, Prospect, ProspectEvent
from datalayer.prospects import is_paused
from datalayer.whatsapp import canonical_number


@transaction.atomic
def start_pilot(phone, *, retry_cycle_id=None):
    prospect = Prospect.objects.select_for_update().get(phone=phone)
    conversation = Conversation.objects.select_for_update().get(
        prospect=prospect, channel="whatsapp"
    )
    if canonical_number(conversation.whatsapp_sender) != phone.lstrip("+"):
        raise ValidationError("El remitente WhatsApp no corresponde al número autorizado.")
    active = prospect.followup_cycles.filter(closed_at__isnull=True).first()
    if active:
        if active.pilot and active.pilot.get("recipient") == phone:
            if retry_cycle_id is not None and active.pilot.get("retry_of") != retry_cycle_id:
                raise ValidationError("Ya existe otro piloto abierto; no se sustituye.")
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
    if retry_cycle_id is not None:
        if prospect.followup_cycles.filter(pilot__retry_of=retry_cycle_id).exists():
            raise ValidationError(
                "Este ciclo ya tiene una repetición; revisa el resultado más reciente."
            )
        previous = prospect.followup_cycles.get(pk=retry_cycle_id, closed_at__isnull=False)
        if not previous.pilot or previous.pilot.get("recipient") != phone:
            raise ValidationError("El ciclo anterior no corresponde a este piloto/destinatario.")
        failed = set(
            previous.attempts.filter(
                status="failed",
                delivery__status="failed",
                reason__in=["meta_http_401", "whatsapp_token_expired", "whatsapp_auth_failed"],
            ).values_list("day", flat=True)
        )
        days = [day for day in DAYS if day in failed]
        if not days:
            raise ValidationError("No hay envíos rechazados por credenciales para repetir.")
        cycle.pilot.update(
            {
                "days": days,
                "retry_of": previous.pk,
                "remaining_from_day": days[0],
                "remaining_start_at": (now + timedelta(minutes=1)).isoformat(),
                "interval_minutes": 5,
                "silence_minutes": 2,
            }
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
            f"PRUEBA: repetición autorizada de {len(cycle_days(cycle))} envíos rechazados por "
            f"credenciales del ciclo {retry_cycle_id}. Cada cinco minutos, silencio de dos. "
            "Se conserva el registro anterior y se retira el permiso temporal al cerrar."
        )
        if retry_cycle_id is not None
        else (
            "PRUEBA: permiso explícito de Guillermo para ocho seguimientos cada 30 minutos. "
            "Primeros tres: operación, municipio, tipo/municipio; después selección contextual. "
            "Silencio mínimo de cinco minutos. No modifica citas ni el calendario normal. "
            "Al terminar se retira el permiso temporal."
        ),
    )
    assert end_date(cycle) > now
    return cycle, True


@transaction.atomic
def accelerate_pilot(cycle_id):
    cycle = FollowupCycle.objects.select_for_update().select_related("prospect").get(pk=cycle_id)
    if not cycle.pilot or cycle.closed_at or not cycle.permission:
        raise ValidationError("Se requiere un piloto abierto con permiso vigente.")
    if cycle.pilot.get("recipient") != cycle.prospect.phone or cycle.prospect.contact_opted_out:
        raise ValidationError("El destinatario o su permiso cambiaron.")
    attempts = list(cycle.attempts.select_for_update())
    if any(a.status in {"queued", "preparing", "prepared"} for a in attempts):
        raise ValidationError("Hay un intento en curso; espera a que termine antes de reprogramar.")
    remaining = [day for day in cycle_days(cycle) if day not in {a.day for a in attempts}]
    if not remaining:
        raise ValidationError("No quedan intentos sin ejecutar.")
    # Repeating the command must not keep postponing the same pending attempts.
    if cycle.pilot.get("interval_minutes") == 5 and cycle.pilot.get("silence_minutes") == 2:
        return cycle
    now = timezone.now()
    first_due = max(
        now + timedelta(minutes=1), min(due_date(cycle, remaining[0]), now + timedelta(minutes=5))
    )
    cycle.pilot = {
        **cycle.pilot,
        "remaining_from_day": remaining[0],
        "remaining_start_at": first_due.isoformat(),
        "interval_minutes": 5,
        "silence_minutes": 2,
    }
    cycle.save(update_fields=["pilot"])
    ProspectEvent.objects.create(
        prospect=cycle.prospect,
        description=(
            "PRUEBA: Guillermo autorizó acelerar solo los intentos restantes a cada cinco minutos "
            "y reducir el silencio mínimo a dos minutos. Se conservan los intentos ya ejecutados, "
            "el número autorizado y la restauración de la baja al cerrar."
        ),
    )
    return cycle
