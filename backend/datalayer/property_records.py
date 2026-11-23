"""The property is the source of commercial facts, even when no operation closes."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field

from datalayer.closing_schemas import Characteristics, ClosingData
from datalayer.models import Capture, CaptureEvent, Property, PropertyEvent


class PrivatePropertyData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    private_address: str = Field(default="", max_length=240)
    zone_type: str = Field(default="colonia", pattern="^(colonia|barrio|localidad)$")
    location_mode: str = Field(default="address", pattern="^(address|reference)$")
    location_reference: str = Field(default="", max_length=500)
    rural_identification: str = Field(default="", max_length=500)
    rural_reference: str = Field(default="", max_length=500)
    characteristics: Characteristics = Field(default_factory=Characteristics)


def capture_facts(raw):
    traits = {key: raw[key] for key in Characteristics.model_fields if key in raw}
    if traits.get("age_years") is not None and not traits.get("age_type"):
        traits["age_type"] = "years"
    return PrivatePropertyData.model_validate(
        {
            "private_address": raw.get("private_address", ""),
            "location_mode": raw.get("location_mode", "address"),
            "location_reference": raw.get("location_reference", ""),
            "zone_type": "localidad" if raw.get("location_mode") == "reference" else "colonia",
            "rural_identification": raw.get("rural_identification", ""),
            "rural_reference": raw.get("rural_reference", ""),
            "characteristics": traits,
        }
    )


def facts(offer):
    if offer.origin == "easybroker":
        from datalayer.easybroker.imports import closed
        from datalayer.easybroker.profiles import current_facts

        if not closed(offer):
            return current_facts(offer)
    capture = Capture.objects.filter(property=offer).first()
    raw = capture.data if capture else {}
    private = (
        capture_facts(raw) if capture else PrivatePropertyData.model_validate(offer.private_data)
    )
    traits = private.characteristics.model_dump(mode="json")
    for key in ("bedrooms", "bathrooms", "parking"):
        if not capture or traits[key] is None:
            traits[key] = (
                str(offer.bathrooms)
                if key == "bathrooms" and offer.bathrooms is not None
                else getattr(offer, key)
            )
    traits["not_applicable"] = [
        key for key in traits.get("not_applicable", []) if traits.get(key) is None
    ]
    return ClosingData.model_validate(
        {
            "operation": offer.operation,
            "kind": offer.kind,
            "subtype": offer.subtype,
            "state": offer.state,
            "municipality": offer.municipality,
            "zone_type": private.zone_type,
            "zone": offer.neighborhood,
            "address_mode": "rural" if private.location_mode == "reference" else "urban",
            "address_text": private.private_address,
            "rural_identification": private.rural_identification,
            "rural_reference": private.rural_reference,
            "access_notes": private.location_reference,
            "currency": offer.currency or "",
            "construction_m2": offer.area_m2,
            "land_m2": raw.get("land_m2", offer.land_m2),
            "private_m2": raw.get("private_m2", offer.private_m2),
            "characteristics": traits,
            "responsible_id": offer.advisor_id,
        }
    )


def snapshot(offer):
    offer = Property.objects.get(pk=offer.pk)
    from datalayer.easybroker.publication import source_evidence

    return {
        "source": source_evidence(offer),
        "reference": offer.reference,
        "title": offer.title,
        "published": offer.published,
        "withdrawn_at": offer.withdrawn_at.isoformat() if offer.withdrawn_at else None,
        "asking_price": str(offer.price) if offer.price is not None else None,
        "asking_currency": offer.currency,
        "description": offer.description,
        "internal_notes": offer.internal_notes,
        "updated_at": offer.updated_at.isoformat(),
        "facts": facts(offer).model_dump(mode="json"),
    }


def record(offer, actor, action, reason=""):
    return PropertyEvent.objects.create(
        property=offer,
        actor=actor,
        actor_email=actor.email if actor else "",
        action=action,
        reason=reason[:1000],
        snapshot=snapshot(offer),
    )


def record_capture(capture, actor, action, reason=""):
    private = capture_facts(capture.data).model_dump(mode="json")
    safe = {
        key: capture.data.get(key)
        for key in (
            "operation",
            "kind",
            "subtype",
            "state",
            "municipality",
            "neighborhood",
            "price",
            "currency",
            "land_m2",
            "area_m2",
            "private_m2",
        )
    }
    safe["private_data"] = private
    CaptureEvent.objects.create(
        capture=capture,
        actor=actor,
        actor_email=actor.email if actor else "",
        action=action,
        summary=reason[:1000],
        snapshot=safe,
    )
    if capture.property_id:
        offer = Property.objects.get(pk=capture.property_id)
        if action == "withdraw":
            offer.withdrawn_at = timezone.now()
            offer.save(update_fields=["withdrawn_at"])
        record(offer, actor, action, reason)


@transaction.atomic
def withdraw(actor, offer_id, reason, expected):
    from datalayer.closings import ClosingConflict, ensure_offer_open, staff

    staff(actor)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValidationError("Indica el motivo de la retirada, hasta 1000 caracteres.")
    capture = Capture.objects.select_for_update().filter(property_id=offer_id).first()
    offer = Property.objects.select_for_update().get(pk=offer_id)
    ensure_offer_open(offer)
    if snapshot(offer) != expected:
        raise ClosingConflict("La propiedad cambió. Revisa su ficha antes de continuar.")
    if capture:
        from datalayer.captures import review

        review(
            capture.pk,
            actor,
            {"action": "withdraw", "revision": capture.revision, "summary": reason},
        )
    else:
        was_published = offer.published
        offer.published = False
        offer.withdrawn_at = timezone.now()
        offer.save(update_fields=["published", "withdrawn_at", "updated_at"])
        record(offer, actor, "withdraw", reason)
        from datalayer.inventory import notify_unpublished

        notify_unpublished(offer, was_published)
    return offer


@transaction.atomic
def result(actor, offer_id):
    from datalayer import closings
    from datalayer.inventory import managed_property
    from datalayer.models import Closing

    closings.staff(actor)
    Capture.objects.select_for_update().filter(property_id=offer_id).first()
    offer = Property.objects.select_for_update().get(pk=offer_id)
    profile = facts(offer)
    return {
        "property": managed_property(offer),
        "source": snapshot(offer),
        "profile": profile.model_dump(mode="json"),
        "missing_profile": [
            key
            for key in profile.missing_required()
            if key not in {"price", "year", "month", "day"}
        ],
        "operations": [
            closings.output(row, history=True)
            for row in Closing.objects.filter(offer=offer)
            .exclude(status="draft")
            .order_by("-created_at")
        ],
        "history": [
            {
                "id": row.pk,
                "action": row.action,
                "reason": row.reason,
                "actor_id": row.actor_id,
                "actor_email": row.actor_email,
                "at": row.created_at.isoformat(),
                "snapshot": row.snapshot,
            }
            for row in offer.record_events.order_by("created_at")
        ],
        "can_confirm": closings.can_confirm(actor),
        "admin": actor.is_superuser,
    }


@transaction.atomic
def prepare(actor, offer_id, value):
    from datalayer import closings
    from datalayer.models import User

    closings.staff(actor)
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    closings.authorized(actor)
    Capture.objects.select_for_update().filter(property_id=offer_id).first()
    offer = Property.objects.select_for_update().get(pk=offer_id)
    closings.ensure_offer_open(offer)
    if snapshot(offer) != value.get("source"):
        raise closings.ClosingConflict(
            "La ficha cambió. Vuelve a revisar los datos de la propiedad."
        )
    when = date.fromisoformat(value["date"])
    data = facts(offer).model_dump(mode="json")
    data.update(
        price=value.get("price"),
        currency=value.get("currency", offer.currency),
        year=when.year,
        month=when.month,
        day=when.day,
        buyer_id=value.get("buyer_id"),
        is_test=value.get("is_test", False),
        notes=value.get("notes", ""),
    )
    data = ClosingData.model_validate(data)
    if data.missing_required():
        raise ValidationError(
            "Completa los datos pendientes en la ficha de la propiedad antes de marcarla como vendida o rentada."
        )
    row = closings.create_draft(
        actor,
        request_id=value["request_id"],
        data=data.model_dump(mode="json"),
        origin="current",
        offer_id=offer.pk,
    )
    return closings.preview(actor, row["id"])


@transaction.atomic
def restore(actor, offer_id, reason, expected):
    from datalayer import closings

    closings.staff(actor)
    capture = Capture.objects.select_for_update().filter(property_id=offer_id).first()
    offer = Property.objects.select_for_update().get(pk=offer_id)
    closings.ensure_offer_open(offer)
    if snapshot(offer) != expected:
        raise closings.ClosingConflict("La propiedad cambió. Actualiza su ficha.")
    if (
        not (
            offer.withdrawn_at or capture and capture.status in {"withdrawn", "rejected", "expired"}
        )
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 1000
    ):
        raise ValidationError(
            "Indica el motivo para volver a comercializar una propiedad retirada."
        )
    offer.withdrawn_at = None
    offer.published = False
    offer.save(update_fields=["withdrawn_at", "published", "updated_at"])
    if capture:
        capture.status = "submitted"
        capture.verified_at = None
        capture.revision += 1
        capture.save(update_fields=["status", "verified_at", "revision", "updated_at"])
        record_capture(capture, actor, "restore", reason)
    else:
        record(offer, actor, "restore", reason)
    return offer
