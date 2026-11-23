"""Private, transactional registry of realized operations and their history."""

import hashlib
import json
from datetime import date
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from datalayer.closing_schemas import ClosingData
from datalayer.models import (
    Advisor,
    Capture,
    CaptureEvent,
    Closing,
    ClosingRequest,
    ClosingRevision,
    Conversation,
    FollowupAttempt,
    FollowupCycle,
    Notification,
    OfferClosure,
    PhysicalProperty,
    PhysicalPropertyLink,
    Property,
    Prospect,
    ProspectEvent,
    SearchIntent,
    User,
)


class ClosingConflict(Exception):
    pass


def staff(actor):
    if (
        not actor
        or not actor.is_authenticated
        or not User.objects.filter(pk=actor.pk, is_active=True, is_staff=True).exists()
    ):
        raise PermissionDenied("Se requiere acceso del equipo.")


def can_confirm(actor):
    return bool(actor and actor.is_authenticated and actor.is_active and actor.is_staff)


def authorized(actor):
    staff(actor)


def data_of(revision):
    return ClosingData.model_validate(
        {name: getattr(revision, name) for name in ClosingData.model_fields}
    )


def current(closing):
    return closing.revisions.get(number=closing.revision)


def append(
    closing,
    actor,
    data,
    action,
    status,
    reason="",
    *,
    confirmed_at=None,
    confirmed_by_id=None,
    reversal_date=None,
):
    values = data.model_dump()
    values["characteristics"] = data.characteristics.model_dump(mode="json")
    values["charges"] = [row.model_dump(mode="json") for row in data.charges]
    row = ClosingRevision.objects.create(
        source_evidence=source_signature(closing) or {},
        closing=closing,
        number=closing.revision + 1,
        actor=actor,
        actor_email=actor.email,
        action=action,
        status=status,
        reason=reason,
        confirmed_at=confirmed_at,
        confirmed_by_id=confirmed_by_id,
        reversal_date=reversal_date,
        **values,
    )
    closing.revision, closing.status = row.number, status
    closing.save(update_fields=["revision", "status", "updated_at"])
    return row


def output(closing, *, history=False):
    row = current(closing)
    data = data_of(row)
    result = {
        "id": str(closing.pk),
        "physical_property_id": str(closing.physical_property_id),
        "canonical_physical_property_id": str(identity_group(closing.physical_property_id)[0]),
        "offer_id": closing.offer_id,
        "origin": closing.origin,
        "author_id": closing.author_id,
        "revision": closing.revision,
        "status": closing.status,
        "created_at": closing.created_at.isoformat(),
        "data": data.model_dump(mode="json"),
        "source_evidence": row.source_evidence,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "confirmed_by_id": row.confirmed_by_id,
        "reversal_date": row.reversal_date.isoformat() if row.reversal_date else None,
        "missing_required": data.missing_required(),
        "missing_characteristics": data.missing_characteristics(),
    }
    if history:
        members = identity_group(closing.physical_property_id)[1]
        result["identity_links"] = [
            {
                "source_id": str(link.source_id),
                "target_id": str(link.target_id),
                "actor_id": link.actor_id,
                "actor_email": link.actor_email,
                "reason": link.reason,
                "at": link.created_at.isoformat(),
            }
            for link in PhysicalPropertyLink.objects.filter(source_id__in=members).order_by(
                "created_at"
            )
        ]
        result["history"] = [
            {
                "number": item.number,
                "action": item.action,
                "status": item.status,
                "actor_id": item.actor_id,
                "actor_email": item.actor_email,
                "at": item.created_at.isoformat(),
                "reason": item.reason,
                "data": data_of(item).model_dump(mode="json"),
                "source_evidence": item.source_evidence,
                "reversal_date": item.reversal_date.isoformat() if item.reversal_date else None,
            }
            for item in closing.revisions.order_by("number")
        ]
        result["offer_periods"] = [
            {
                "offer_id": period.offer_id,
                "period": period.period,
                "closed_at": period.closed_at.isoformat(),
                "reopened_at": period.reopened_at.isoformat() if period.reopened_at else None,
                "reopened_by_id": period.reopened_by_id,
                "reason": period.reopen_reason,
            }
            for period in OfferClosure.objects.filter(closing=closing)
        ]
    return result


def validate_links(data):
    if data.responsible_id and not Advisor.objects.filter(pk=data.responsible_id).exists():
        raise ValidationError("No encontramos al asesor responsable.")
    if data.buyer_id and not Prospect.objects.filter(pk=data.buyer_id).exists():
        raise ValidationError("No encontramos al comprador o arrendatario.")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def identity_group(identity_id):
    links = dict(PhysicalPropertyLink.objects.values_list("source_id", "target_id"))

    def root(value):
        seen = set()
        while value in links:
            if value in seen:
                raise ClosingConflict("La vinculación del inmueble requiere revisión.")
            seen.add(value)
            value = links[value]
        return value

    canonical = root(UUID(str(identity_id)))
    members = {canonical} | {key for key in links if root(key) == canonical}
    return canonical, members


@transaction.atomic
def link_identities(actor, source_id, target_id, *, reason, request_id):
    staff(actor)
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    authorized(actor)
    payload = {
        "action": "link_identities",
        "source": str(source_id),
        "target": str(target_id),
        "reason": reason,
    }
    prior = receipt(actor, request_id, payload)
    if prior:
        return prior
    if not reason.strip() or len(reason) > 1000:
        raise ValidationError("Indica el motivo de la vinculación, hasta 1000 caracteres.")
    # Explicit, rare human linkage: serialize identity changes, without blocking FK inserts.
    list(PhysicalProperty.objects.select_for_update(no_key=True).order_by("pk"))
    source, _ = identity_group(source_id)
    target, _ = identity_group(target_id)
    PhysicalProperty.objects.get(pk=source)
    PhysicalProperty.objects.get(pk=target)
    if source == target:
        raise ClosingConflict("Los registros ya corresponden al mismo inmueble.")
    PhysicalPropertyLink.objects.create(
        source_id=source,
        target_id=target,
        actor=actor,
        actor_email=actor.email,
        reason=reason.strip(),
    )
    return remember(actor, request_id, payload, None, {"physical_property_id": str(target)})


def receipt(actor, request_id, payload):
    row = ClosingRequest.objects.filter(pk=UUID(str(request_id))).first()
    if row:
        if row.actor_id != actor.pk or row.fingerprint != fingerprint(payload):
            raise ClosingConflict("Esa solicitud ya se utilizó con otros datos.")
        return row.result
    return None


def remember(actor, request_id, payload, closing, result):
    ClosingRequest.objects.create(
        id=UUID(str(request_id)),
        actor=actor,
        closing=closing,
        fingerprint=fingerprint(payload),
        result=result,
    )
    return result


@transaction.atomic
def create_draft(
    actor, *, request_id, data, origin="historical", offer_id=None, physical_property_id=None
):
    staff(actor)
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    staff(actor)
    data = ClosingData.model_validate(data)
    payload = {
        "action": "create",
        "data": data.model_dump(mode="json"),
        "origin": origin,
        "offer": offer_id,
        "physical": str(physical_property_id) if physical_property_id else None,
    }
    prior = receipt(actor, request_id, payload)
    if prior:
        return prior
    if origin not in {"current", "historical"} or origin == "current" and not offer_id:
        raise ValidationError("Selecciona una oferta para registrar un cierre actual.")
    offer = None
    if offer_id:
        # Legacy offers created by existing callers may not have an identity yet.
        list(Capture.objects.select_for_update().filter(property_id=offer_id))
        offer = Property.objects.select_for_update().get(pk=offer_id)
        if not offer.physical_property_id:
            offer.physical_property = PhysicalProperty.objects.create()
            offer.save(update_fields=["physical_property"])
        if (
            physical_property_id
            and identity_group(offer.physical_property_id)[0]
            != identity_group(physical_property_id)[0]
        ):
            raise ValidationError("La oferta pertenece a otro inmueble.")
        identity = offer.physical_property
    else:
        identity = (
            PhysicalProperty.objects.get(pk=identity_group(physical_property_id)[0])
            if physical_property_id
            else PhysicalProperty.objects.create()
        )
    validate_links(data)
    closing = Closing.objects.create(
        physical_property=identity, offer=offer, origin=origin, author=actor
    )
    append(closing, actor, data, "create", "draft")
    return remember(actor, request_id, payload, closing, output(closing))


@transaction.atomic
def update_draft(actor, closing_id, *, revision, data):
    staff(actor)
    row = Closing.objects.select_for_update().get(pk=closing_id)
    if row.status != "draft":
        raise ClosingConflict("Un cierre confirmado requiere una corrección con historial.")
    if (
        row.author_id != actor.pk
        and not User.objects.filter(pk=actor.pk, is_superuser=True).exists()
    ):
        raise PermissionDenied("Solo el autor o un administrador puede editar este borrador.")
    if row.revision != revision:
        raise ClosingConflict("El borrador cambió. Actualiza antes de continuar.")
    data = ClosingData.model_validate(data)
    validate_links(data)
    append(row, actor, data, "edit", "draft")
    return output(row)


@transaction.atomic
def delete_draft(actor, closing_id, *, revision):
    staff(actor)
    row = Closing.objects.select_for_update().get(pk=closing_id)
    if row.status != "draft" or row.revisions.filter(confirmed_at__isnull=False).exists():
        raise ClosingConflict("Solo se pueden borrar borradores nunca confirmados.")
    if (
        row.author_id != actor.pk
        and not User.objects.filter(pk=actor.pk, is_superuser=True).exists()
    ):
        raise PermissionDenied("Solo el autor o un administrador puede borrar este borrador.")
    if row.revision != revision:
        raise ClosingConflict("El borrador cambió. Actualiza antes de continuar.")
    ClosingRequest.objects.filter(closing=row).delete()
    row.delete()


def ensure_offer_open(offer):
    if OfferClosure.objects.filter(offer=offer, period=offer.commercialization_round).exists():
        raise ValidationError(
            "La oferta terminó por cierre. Requiere reapertura expresa si el cierre fue anulado."
        )


@transaction.atomic
def resolve_search(actor, closing_id, intent_id, *, request_id):
    staff(actor)
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    authorized(actor)
    payload = {"action": "resolve_search", "closing": str(closing_id), "intent": str(intent_id)}
    prior = receipt(actor, request_id, payload)
    if prior:
        return prior
    initial = SearchIntent.objects.get(pk=intent_id)
    # Existing follow-up controls acquire conversations before the prospect.
    list(
        Conversation.objects.select_for_update(no_key=True)
        .filter(prospect_id=initial.prospect_id)
        .order_by("pk")
    )
    prospect = Prospect.objects.select_for_update().get(pk=initial.prospect_id)
    intent = SearchIntent.objects.select_for_update().get(pk=intent_id)
    closing = Closing.objects.select_for_update().get(pk=closing_id)
    revision = current(closing)
    if closing.status != "confirmed" or closing.origin != "current":
        raise ClosingConflict(
            "Solo un cierre actual confirmado puede atender una búsqueda vigente."
        )
    if revision.buyer_id != intent.prospect_id:
        raise ValidationError(
            "La búsqueda debe pertenecer al comprador o arrendatario seleccionado."
        )
    if intent.resolved_at:
        raise ClosingConflict("Esta búsqueda ya fue atendida.")
    from datalayer.followups import criteria_for

    cycle = FollowupCycle.objects.select_for_update().filter(intent=intent).first()
    if cycle:
        intent.criteria = criteria_for(cycle)
    now = timezone.now()
    intent.resolved_by, intent.resolved_at, intent.closing = actor, now, closing
    intent.save(update_fields=["criteria", "resolved_by", "resolved_at", "closing"])
    if cycle and cycle.closed_at is None:
        cycle.closed_at, cycle.reason = now, "search_resolved"
        cycle.save(update_fields=["closed_at", "reason"])
    if cycle:
        FollowupAttempt.objects.filter(
            cycle=cycle, status__in=["queued", "preparing", "prepared", "review"]
        ).update(status="skipped", reason="search_resolved", updated_at=now)
    ProspectEvent.objects.create(
        prospect=prospect,
        actor=actor,
        description="Búsqueda seleccionada atendida por cierre. Se conserva el permiso general de contacto.",
    )
    return remember(
        actor,
        request_id,
        payload,
        closing,
        {"intent_id": str(intent.pk), "resolved_at": now.isoformat()},
    )


def duplicates(closing, data):
    rows = (
        Closing.objects.filter(
            physical_property_id__in=identity_group(closing.physical_property_id)[1]
        )
        .exclude(pk=closing.pk)
        .exclude(status="draft")
    )
    return list(
        ClosingRevision.objects.filter(
            closing__in=rows,
            number=F("closing__revision"),
            operation=data.operation,
            year=data.year,
            month=data.month,
            day=data.day,
        )
        .order_by("closing_id")
        .values_list("closing_id", flat=True)
    )


def source_signature(closing):
    if closing.origin != "current" or not closing.offer_id:
        return None
    offer = Property.objects.get(pk=closing.offer_id)
    capture = Capture.objects.filter(property=offer).first()
    from datalayer.easybroker.publication import source_evidence

    signature = {
        "external_source": source_evidence(offer),
        "offer": offer.pk,
        "updated_at": offer.updated_at.isoformat(),
        "period": offer.commercialization_round,
        "capture_revision": capture.revision if capture else None,
        "agreements": list(capture.agreements.order_by("pk").values("pk", "ended_at", "expires_at"))
        if capture
        else [],
    }
    return json.loads(json.dumps(signature, cls=DjangoJSONEncoder))


def preview(actor, closing_id):
    staff(actor)
    closing = Closing.objects.get(pk=closing_id)
    data = data_of(current(closing))
    matches = [str(value) for value in duplicates(closing, data)]
    signature = {
        "identity_group": sorted(
            str(value) for value in identity_group(closing.physical_property_id)[1]
        ),
        "revision": closing.revision,
        "source": source_signature(closing),
        "duplicates": matches,
        "duplicate_revisions": list(
            Closing.objects.filter(pk__in=matches)
            .order_by("pk")
            .values_list("pk", "revision", "status")
        ),
    }
    return {
        **output(closing),
        "preview_token": fingerprint(signature),
        "duplicates": matches,
        "effects": {
            "ends_offer": closing.offer_id if closing.origin == "current" else None,
            "changes_search": False,
            "sends_whatsapp": False,
        },
    }


def notify_future_visits(offer, closing, actor):
    from worker.dispatch import enqueue_notification

    for appointment in offer.appointments.filter(
        status__in=["pending", "confirmed", "review"], end__gt=timezone.now()
    ):
        for advisor_id in {appointment.advisor_id, appointment.prospect.advisor_id} - {None}:
            notice, created = Notification.objects.get_or_create(
                event_key=f"closing:{closing.pk}:visit:{appointment.pk}:{advisor_id}",
                defaults={
                    "conversation": appointment.conversation,
                    "advisor_id": advisor_id,
                    "reason": "appointment",
                    "summary": "Propiedad cerrada con visita pendiente. El asesor debe revisar; la cita se conserva.",
                    "payload": {},
                },
            )
            if created:
                enqueue_notification(notice.pk)


@transaction.atomic
def command(
    actor,
    closing_id,
    *,
    action,
    request_id,
    revision,
    reason="",
    data=None,
    preview_token=None,
    reviewed_duplicates=None,
    reversal_date=None,
):
    staff(actor)
    if not isinstance(reason, str) or len(reason) > 1000:
        raise ValidationError("El motivo debe tener hasta 1000 caracteres.")
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    authorized(actor)
    payload = {
        "action": action,
        "closing": str(closing_id),
        "revision": revision,
        "reason": reason,
        "data": data,
        "preview": preview_token,
        "duplicates": reviewed_duplicates,
        "reversal_date": reversal_date,
    }
    prior = receipt(actor, request_id, payload)
    if prior:
        return prior
    original = Closing.objects.get(pk=closing_id)
    _, members = identity_group(original.physical_property_id)
    list(
        PhysicalProperty.objects.select_for_update(no_key=True)
        .filter(pk__in=members)
        .order_by("pk")
    )
    if members != identity_group(original.physical_property_id)[1]:
        raise ClosingConflict("Cambió la vinculación del inmueble. Revisa el resumen actualizado.")
    capture = None
    offer = None
    if original.offer_id:
        capture = Capture.objects.select_for_update().filter(property_id=original.offer_id).first()
        offer = Property.objects.select_for_update().get(pk=original.offer_id)
    closing = Closing.objects.select_for_update().get(pk=closing_id)
    if closing.revision != revision:
        raise ClosingConflict("El cierre cambió. Revisa el resumen actualizado.")
    old = current(closing)
    values = data_of(old)
    now = timezone.now()
    if action == "confirm":
        if closing.status != "draft":
            raise ClosingConflict("Este registro ya fue confirmado.")
        if offer and offer.origin == "easybroker" and old.source_evidence != source_signature(closing):
            raise ClosingConflict("El origen cambió. Prepara el cierre con la ficha vigente.")
        missing = values.missing_required()
        if missing:
            raise ValidationError(
                {key: "Completa este dato antes de confirmar." for key in missing}
            )
        validate_links(values)
        if date(values.year, values.month, values.day) > timezone.localdate():
            raise ValidationError("Un cierre realizado no puede tener fecha futura.")
        summary = preview(actor, closing.pk)
        if not preview_token or summary["preview_token"] != preview_token:
            raise ClosingConflict("Revisa el resumen: cambiaron los datos o las coincidencias.")
        if set(reviewed_duplicates or []) != set(summary["duplicates"]):
            raise ClosingConflict("Revisa los posibles cierres duplicados antes de confirmar.")
        if closing.origin == "current":
            if (
                offer.physical_property_id != closing.physical_property_id
                or offer.operation != values.operation
            ):
                raise ClosingConflict(
                    "La oferta no corresponde al inmueble u operación del cierre."
                )
            ensure_offer_open(offer)
            if offer.origin == "easybroker":
                from datalayer.easybroker.profiles import freeze_private_facts

                freeze_private_facts(offer)
            OfferClosure.objects.create(
                offer=offer, period=offer.commercialization_round, closing=closing, closed_at=now
            )
            offer.published = False
            offer.withdrawn_at = None
            offer.save(update_fields=["published", "withdrawn_at", "updated_at"])
            if capture:
                capture.agreements.filter(ended_at__isnull=True).update(ended_at=now)
                capture.status = "closed"
                capture.revision += 1
                capture.save(update_fields=["status", "revision", "updated_at"])
                CaptureEvent.objects.create(
                    capture=capture,
                    actor=actor,
                    actor_email=actor.email,
                    action="closed",
                    summary=f"Cierre {closing.pk}",
                )
            notify_future_visits(offer, closing, actor)
        append(
            closing,
            actor,
            values,
            "confirm",
            "confirmed",
            confirmed_at=now,
            confirmed_by_id=actor.pk,
        )
    elif action in {"correct", "annul", "reverse"}:
        if closing.status != "confirmed":
            raise ClosingConflict("Esta acción requiere un cierre confirmado vigente.")
        if not reason.strip():
            raise ValidationError("Indica el motivo del cambio.")
        if action == "correct":
            values = ClosingData.model_validate(data)
            if values.missing_required():
                raise ValidationError(
                    "La corrección debe conservar completos los datos obligatorios."
                )
            validate_links(values)
            if date(values.year, values.month, values.day) > timezone.localdate():
                raise ValidationError("Un cierre realizado no puede tener fecha futura.")
            if closing.origin == "current" and values.operation != offer.operation:
                raise ValidationError("El tipo de operación debe corresponder a la oferta cerrada.")
        reverse_date = date.fromisoformat(str(reversal_date)) if action == "reverse" else None
        if action == "reverse" and (
            reverse_date < date(values.year, values.month, values.day)
            or reverse_date > timezone.localdate()
        ):
            raise ValidationError("La reversión debe estar entre el cierre y hoy.")
        append(
            closing,
            actor,
            values,
            action,
            {"correct": "confirmed", "annul": "annulled", "reverse": "reversed"}[action],
            reason.strip(),
            confirmed_at=old.confirmed_at,
            confirmed_by_id=old.confirmed_by_id,
            reversal_date=reverse_date,
        )
    elif action == "reopen":
        if closing.status != "annulled" or closing.origin != "current" or not offer:
            raise ClosingConflict(
                "Solo se reabre una oferta cuyo cierre actual fue anulado por error."
            )
        if not reason.strip():
            raise ValidationError("Indica el motivo de la reapertura.")
        period = (
            OfferClosure.objects.select_for_update()
            .filter(offer=offer, period=offer.commercialization_round)
            .first()
        )
        if not period or period.closing_id != closing.pk or period.reopened_at:
            raise ClosingConflict("La oferta ya cambió de periodo de comercialización.")
        period.reopened_at, period.reopened_by, period.reopen_reason = now, actor, reason.strip()
        period.save(update_fields=["reopened_at", "reopened_by", "reopen_reason"])
        offer.commercialization_round += 1
        offer.published = False
        offer.save(update_fields=["commercialization_round", "published", "updated_at"])
        if capture:
            capture.status = "submitted"
            capture.verified_at = None
            capture.revision += 1
            capture.save(update_fields=["status", "verified_at", "revision", "updated_at"])
            CaptureEvent.objects.create(
                capture=capture,
                actor=actor,
                actor_email=actor.email,
                action="closing_reopened",
                summary=reason.strip(),
            )
    else:
        raise ValidationError("Acción de cierre inválida.")
    if offer:
        from datalayer.property_records import record

        record(offer, actor, action, reason)
    return remember(actor, request_id, payload, closing, output(closing, history=True))
