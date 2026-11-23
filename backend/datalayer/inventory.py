from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, DecimalField, F, IntegerField, Q, Value, When
from django.utils import timezone

from datalayer.models import Property, normalize_zone
from datalayer.schemas import PropertyInput, SearchCriteria

PAGE_SIZE = 3
OPTIONAL_FILTERS = {
    "min_bedrooms": ("bedrooms", "gte"),
    "min_bathrooms": ("bathrooms", "gte"),
    "min_parking": ("parking", "gte"),
    "furnished": ("furnished", "exact"),
    "accepts_pets": ("accepts_pets", "exact"),
    "near_schools": ("near_schools", "exact"),
}


def property_fields(prop, unconfirmed=None):
    return {
        "id": prop.pk,
        "reference": prop.reference,
        "title": prop.title,
        "operation": prop.operation,
        "kind": prop.kind,
        "currency": prop.currency,
        "state": prop.state,
        "subtype": prop.subtype,
        "is_presale": prop.is_presale,
        "public_location": prop.public_location,
        "details": prop.details,
        "municipality": prop.municipality,
        "neighborhood": prop.neighborhood,
        "public_address": prop.public_address,
        "price": str(prop.price) if prop.price is not None else None,
        "price_visible": prop.price_visible,
        "bedrooms": prop.bedrooms,
        "bathrooms": str(prop.bathrooms) if prop.bathrooms is not None else None,
        "parking": prop.parking,
        "area_m2": str(prop.area_m2) if prop.area_m2 is not None else None,
        "furnished": prop.furnished,
        "accepts_pets": prop.accepts_pets,
        "near_schools": prop.near_schools,
        "description": prop.description,
        "photos": prop.photos,
        "unconfirmed": unconfirmed or [],
    }


def public_property(prop, unconfirmed=None):
    if prop.origin == "easybroker":
        from datalayer.easybroker.publication import public_projection

        # Re-read under the same offer lock used by privacy/publication writes.
        with transaction.atomic():
            current = Property.objects.select_for_update().get(pk=prop.pk)
            return public_projection(current, property_fields(current, unconfirmed))
    return property_fields(prop, unconfirmed)


def managed_property(prop):
    from datalayer.models import OfferClosure
    from datalayer.property_records import capture_facts

    period = (
        OfferClosure.objects.filter(offer=prop, period=prop.commercialization_round)
        .select_related("closing")
        .first()
    )
    capture = getattr(prop, "capture", None)
    source_current = None
    if prop.origin == "easybroker":
        from datalayer.easybroker.imports import closed
        from datalayer.easybroker.profiles import current_facts

        if not closed(prop):
            source_current = current_facts(prop).model_dump(mode="json")
    status = (
        ("sold" if prop.operation == "sale" else "rented")
        if period
        else "withdrawn"
        if prop.withdrawn_at or capture and capture.status in {"withdrawn", "rejected", "expired"}
        else "available"
    )
    return {
        **property_fields(prop),
        "origin": prop.origin,
        "source_current": source_current,
        "published": prop.published,
        "internal_notes": prop.internal_notes,
        "advisor_id": prop.advisor_id,
        "capture_id": str(prop.capture.pk) if hasattr(prop, "capture") else None,
        "private_data": capture_facts(capture.data).model_dump(mode="json")
        if capture
        else prop.private_data,
        "land_m2": str(prop.land_m2) if prop.land_m2 is not None else None,
        "private_m2": str(prop.private_m2) if prop.private_m2 is not None else None,
        "commercial_status": status,
        "closing_id": str(period.closing_id) if period else None,
        "withdrawn_at": prop.withdrawn_at.isoformat() if prop.withdrawn_at else None,
    }


@transaction.atomic
def save_property(data: PropertyInput, prop=None, *, actor=None):
    from datalayer.property_records import record

    if prop:
        from datalayer.models import Capture

        capture = Capture.objects.select_for_update().filter(property_id=prop.pk).first()
        prop = Property.objects.select_for_update().get(pk=prop.pk)
        if prop.origin != "local":
            raise ValidationError(
                "Revisa esta oferta desde EasyBroker; sus hechos pertenecen al origen."
            )
        from datalayer.closings import ensure_offer_open

        ensure_offer_open(prop)
        if prop.withdrawn_at and data.published:
            raise ValidationError(
                "Primero vuelve a comercializar expresamente la propiedad retirada."
            )
        if capture:
            raise ValidationError(
                {
                    "property": "Edita esta propiedad desde Captación para conservar la revisión y exclusividad."
                }
            )
        record(prop, actor, "before_edit")
    was_published = bool(prop and prop.published)
    prop = prop or Property()
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "private_data":
            if value is not None:
                prop.private_data = data.private_data.model_dump(mode="json")
            continue
        setattr(prop, key, [str(url) for url in value] if key == "photos" else value)
    if prop.is_presale and prop.operation != "sale":
        raise ValidationError({"operation": "Preventa corresponde a venta."})
    prop.full_clean()
    prop.save()
    record(prop, actor, "saved")
    notify_unpublished(prop, was_published)
    return prop


@transaction.atomic
def set_publication(property_id, published, *, actor=None):
    from datalayer.models import Capture

    capture = Capture.objects.select_for_update().filter(property_id=property_id).first()
    if published and capture:
        ensure_publishable(capture)
    prop = Property.objects.select_for_update().get(pk=property_id)
    if prop.origin == "easybroker":
        from datalayer.easybroker.publication import set_imported_publication

        return set_imported_publication(prop, published, actor=actor)
    if published:
        from datalayer.closings import ensure_offer_open

        ensure_offer_open(prop)
        if prop.withdrawn_at:
            raise ValidationError(
                "La propiedad está retirada. Revisa su ficha antes de volver a publicarla."
            )
    was_published = prop.published
    if was_published != published:
        prop.published = published
        prop.save(update_fields=["published", "updated_at"])
        notify_unpublished(prop, was_published)
    if capture and (published or capture.status == "published"):
        capture.status = "published" if published else "accepted"
        capture.save(update_fields=["status", "updated_at"])
    return prop


def ensure_publishable(capture):
    from datalayer.captures import active_agreement

    if (
        capture.status not in {"accepted", "published"}
        or not capture.verified_at
        or not active_agreement(capture)
    ):
        raise ValidationError(
            {"published": "La captación necesita revisión y exclusividad vigente aceptada."}
        )
    if capture.assets.filter(kind="photo").count() < 5:
        raise ValidationError({"published": "La captación necesita cinco fotos."})


def public_inventory():
    # Hide an expired agreement immediately, even between maintenance runs.
    from datalayer.easybroker.publication import eligible_imports

    return (
        Property.objects.filter(published=True, withdrawn_at__isnull=True)
        .exclude(closing_periods__period=F("commercialization_round"))
        .filter(Q(origin="local") | eligible_imports())
        .filter(
            Q(capture__isnull=True)
            | Q(
                capture__status__in=["accepted", "published"],
                capture__agreements__ended_at__isnull=True,
                capture__agreements__expires_at__gt=timezone.now(),
            )
        )
        .distinct()
    )


def notify_unpublished(prop, was_published):
    if was_published and not prop.published:
        from django.utils import timezone

        from datalayer.appointments import notify_appointment

        for appointment in prop.appointments.filter(
            status__in=["pending", "confirmed", "review"], end__gt=timezone.now()
        ):
            notify_appointment(
                appointment,
                f"unpublished:{prop.pk}:{prop.updated_at.isoformat()}:{appointment.pk}",
                "Propiedad despublicada con visita pendiente. El asesor debe decidir; la cita no fue cancelada.",
                notify_client=False,
            )


def search_inventory(criteria: SearchCriteria, offset=0):
    query = public_inventory().annotate(
        public_price=Case(
            When(price_visible=True, then=F("price")),
            default=Value(None),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )
    for field in ("operation", "municipality", "state", "is_presale"):
        value = getattr(criteria, field)
        if value is not None:
            query = query.filter(**{field: value})
    equivalents = {
        "condominium": ("house", "Casa en condominio"),
        "commercial_land": ("land", "Terreno comercial"),
        "industrial_land": ("land", "Terreno industrial"),
    }
    if criteria.kind in equivalents:
        base, subtype = equivalents[criteria.kind]
        query = query.filter(Q(kind=criteria.kind) | Q(kind=base, subtype=subtype))
    elif criteria.kind:
        query = query.filter(
            Q(kind=criteria.kind)
            | Q(kind__in=[key for key, (base, _) in equivalents.items() if base == criteria.kind])
        )
    if criteria.currency or criteria.min_price is not None or criteria.max_price is not None:
        query = query.filter(price_visible=True, currency=criteria.currency or "MXN")
    if criteria.neighborhood:
        query = query.filter(normalized_zone__contains=normalize_zone(criteria.neighborhood))
    if criteria.min_price is not None:
        query = query.filter(public_price__gte=criteria.min_price)
    if criteria.max_price is not None:
        query = query.filter(public_price__lte=criteria.max_price)
    unknown_count = Value(0, output_field=IntegerField())
    checked = []
    for criterion, (field, lookup) in OPTIONAL_FILTERS.items():
        value = getattr(criteria, criterion)
        if value is None:
            continue
        checked.append(field)
        match = Q(**{f"{field}__{lookup}": value})
        if not criteria.verified_only:
            match |= Q(**{f"{field}__isnull": True})
        query = query.filter(match)
        unknown_count += Case(
            When(**{f"{field}__isnull": True}, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    query = query.annotate(unknown_count=unknown_count).order_by(
        "unknown_count", "public_price", "id"
    )
    total = query.count()
    results = [
        public_property(prop, [key for key in checked if getattr(prop, key) is None])
        for prop in query[offset : offset + PAGE_SIZE]
    ]
    return {
        "results": results,
        "total": total,
        "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < total else None,
        "criteria": criteria.model_dump(mode="json"),
    }
