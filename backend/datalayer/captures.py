"""Short, locked transactions for intake, review and exclusive publication."""

import calendar
import hashlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.capture_approval import approval_matches, commercial_data
from datalayer.capture_catalog import CONTRACT_TEXT, CONTRACT_VERSION, KINDS, UPLOAD_LIMITS
from datalayer.capture_errors import CaptureError
from datalayer.capture_mail import can_retry, configuration
from datalayer.capture_schemas import CaptureData
from datalayer.models import (
    Advisor,
    Capture,
    CaptureAgreement,
    CaptureDelivery,
    CaptureEvent,
    Property,
    normalize_zone,
)

BASE_MUNICIPALITIES = {
    normalize_zone(x)
    for x in [
        "Guadalajara",
        "Zapopan",
        "Tlaquepaque",
        "San Pedro Tlaquepaque",
        "Tonalá",
        "Tlajomulco de Zúñiga",
        "El Salto",
        "Juanacatlán",
        "Ixtlahuacán de los Membrillos",
        "Zapotlanejo",
    ]
}


def active_agreement(capture):
    return (
        capture.agreements.filter(ended_at__isnull=True, expires_at__gt=timezone.now())
        .order_by("-accepted_at")
        .first()
    )


def event(capture, actor, action, summary=""):
    CaptureEvent.objects.create(capture=capture, actor=actor, action=action, summary=summary[:1000])


def delivery(channel, key, recipient, subject, body, capture=None, attachment=None):
    from worker.tasks import deliver_capture_message

    row, created = CaptureDelivery.objects.get_or_create(
        event_key=key,
        defaults={
            "channel": channel,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "capture": capture,
            "attachment": attachment or {},
        },
    )
    if created:
        deliver_capture_message.defer(delivery_id=row.pk)
    return row


@transaction.atomic
def request_acceptance(capture):
    """Queue one immutable contract copy for this approval, never accept on an email click."""
    if capture.status != "approved":
        raise ValueError("La solicitud debe estar aprobada antes de solicitar aceptación.")
    from datalayer.capture_contract import contract_snapshot

    snapshot = contract_snapshot(capture)
    row = delivery(
        "email",
        f"capture:{capture.pk}:{capture.revision}:acceptance-request",
        capture.owner.email,
        "Tu propiedad fue aprobada: revisa el acuerdo de exclusividad",
        f"Hola, {capture.data.get('name', 'propietario')}.\n\n"
        f"Nuestro equipo aprobó tu propiedad: {snapshot['title']}.\n"
        "Adjuntamos el contrato de exclusividad de demostración. "
        "El plazo de seis meses comienza cuando lo aceptes, no al recibir este correo.\n\n"
        "Entra a Mis propiedades para revisar el acuerdo y aceptar la exclusividad:\n"
        f"{snapshot['review_url']}\n\n"
        "Si se solicita, inicia sesión con la cuenta que usaste para subir el inmueble. "
        "La liga abrirá directamente esta solicitud. Abrirla no acepta el contrato.\n\n"
        "Después de tu aceptación, el equipo podrá publicar el inmueble. "
        "Este PDF es una copia para revisión, todavía no está aceptado.\n\nMaia",
        capture,
        attachment=snapshot,
    )
    capture.deliveries.filter(
        channel="email", attachment__kind="capture_contract", status="pending"
    ).exclude(pk=row.pk).update(status="superseded", error_code="new_approval")
    return row


def notify(capture, action):
    advisor = capture.advisor
    return delivery(
        "telegram",
        f"capture:{capture.pk}:{capture.revision}:{action}",
        advisor.telegram_chat_id if advisor else "",
        "Captación: " + action,
        f"Solicitud {capture.pk}\n{capture.data.get('title') or KINDS[capture.data.get('kind', 'house')][0]}\nRequiere revisión del equipo.\n{settings.PUBLIC_BASE_URL}/crm?capture={capture.pk}",
        capture,
    )


def output(capture, staff=False):
    from datalayer.google_locations import capture_point

    agreement = active_agreement(capture)
    data = {
        "id": str(capture.pk),
        "data": capture.data,
        "location": capture_point(capture),
        "revision": capture.revision,
        "status": capture.status,
        "property_id": capture.property_id,
        "advisor_id": capture.advisor_id,
        "advisor": {
            "name": capture.advisor.name,
            "whatsapp": capture.advisor.whatsapp,
        }
        if capture.advisor
        else None,
        "pending_request": capture.pending_request,
        "created_at": capture.created_at.isoformat(),
        "updated_at": capture.updated_at.isoformat(),
        "assets": [
            {
                "id": str(a.pk),
                "kind": a.kind,
                "request_id": str(a.request_id),
                "url": f"/api/capture/assets/{a.pk}?v={hashlib.sha256(a.file.name.encode()).hexdigest()[:16]}",
                "content_type": a.content_type,
                "size": a.size,
            }
            for a in capture.assets.all()
        ],
        "agreement": {
            "version": agreement.version,
            "accepted_at": agreement.accepted_at.isoformat(),
            "expires_at": agreement.expires_at.isoformat(),
            "text": agreement.text,
        }
        if agreement
        else None,
        "valuation": capture.valuation if capture.valuation_communicated_at or staff else "",
        "valuation_notes": capture.valuation_notes
        if capture.valuation_communicated_at or staff
        else "",
    }
    if staff:
        data.update(
            owner={
                "email": capture.owner.email,
                "phone": capture.owner.phone,
                "verified": bool(capture.owner.email_verified_at),
            },
            review_notes=capture.review_notes,
            exact_location_approved=capture.exact_location_approved,
            outside_area_approved=capture.outside_area_approved,
            events=list(
                capture.events.order_by("created_at").values("action", "summary", "created_at")
            ),
            mail_configuration=configuration(),
            deliveries=[
                {
                    "id": row.pk,
                    "channel": row.channel,
                    "status": row.status,
                    "error_code": row.error_code,
                    "provider": row.provider,
                    "provider_id": row.provider_id,
                    "can_retry": can_retry(row),
                    "attempts": row.attempts,
                }
                for row in capture.deliveries.order_by("-created_at")
            ],
        )
    return data


def check_complete(capture):
    from datalayer.google_locations import validate_reference

    data = CaptureData.model_validate(capture.data)
    data.check_complete()
    validate_reference(capture.owner, capture.data, complete=True)
    count = capture.assets.filter(kind="photo").count()
    if count < UPLOAD_LIMITS["min_photos"]:
        raise CaptureError(
            "Agrega al menos cinco fotos para enviar la solicitud.",
            code="minimum_photos_required",
            field="photos",
        )
    if count > UPLOAD_LIMITS["max_photos"]:
        raise CaptureError(
            "La solicitud admite hasta 20 fotos. Elimina las que sobren para enviarla.",
            code="photo_limit_exceeded",
            field="photos",
        )
    return data


def check_revision(capture, revision):
    if type(revision) is not int or revision != capture.revision:
        raise ValueError("La solicitud cambió. Actualiza la página antes de guardar.")


@transaction.atomic
def save_draft(owner, data, request_id, revision=None):
    from datalayer.google_locations import validate_reference

    capture, _ = Capture.objects.select_for_update().get_or_create(pk=request_id, owner=owner)
    if capture.owner_id != owner.pk or capture.status != "draft":
        raise ValueError("Solo puedes editar tus borradores.")
    check_revision(capture, revision)
    capture.data = CaptureData.model_validate(data).model_dump(mode="json")
    validate_reference(owner, capture.data)
    capture.revision += 1
    capture.save()
    return capture


@transaction.atomic
def submit(capture_id, owner, revision):
    capture = Capture.objects.select_for_update().get(pk=capture_id, owner=owner)
    if capture.status != "draft":
        return capture
    check_revision(capture, revision)
    if not owner.email_verified_at or not owner.phone:
        raise ValueError("Verifica tu email y completa el teléfono antes de enviar.")
    check_complete(capture)
    capture.status = "submitted"
    capture.advisor = Advisor.objects.filter(is_default=True).first()
    capture.submitted_at = timezone.now()
    capture.revision += 1
    capture.save()
    event(capture, owner, "submitted")
    notify(capture, "Nueva solicitud")
    return capture


def sync_property(capture):
    data = CaptureData.model_validate(capture.data)
    prop = capture.property or Property()
    for key in [
        "operation",
        "is_presale",
        "kind",
        "subtype",
        "state",
        "municipality",
        "neighborhood",
        "price",
        "currency",
        "bedrooms",
        "bathrooms",
        "parking",
        "area_m2",
        "description",
    ]:
        setattr(prop, key, getattr(data, key))
    prop.title = data.title or f"{KINDS[data.kind][0]} en {data.neighborhood or data.municipality}"
    prop.advisor = capture.advisor
    prop.public_address = (
        (data.private_address or data.location_reference) if capture.exact_location_approved else ""
    )
    prop.public_location = {}
    if data.location_ref:
        # A flag, not coordinates: resolve only when rendering a map, never in chat snapshots.
        prop.public_location = {"lookup": True, "approximate": not capture.exact_location_approved}
    if data.latitude is not None:
        prop.public_location = {
            "latitude": data.latitude
            if capture.exact_location_approved
            else round(data.latitude, 2),
            "longitude": data.longitude
            if capture.exact_location_approved
            else round(data.longitude, 2),
            "approximate": not capture.exact_location_approved,
        }
    for key, label in [
        ("furnished", "Amueblado"),
        ("accepts_pets", "Permite mascotas"),
        ("near_schools", "Escuelas cercanas"),
    ]:
        setattr(prop, key, True if label in data.amenities else None)
    prop.photos = [
        f"{settings.PUBLIC_BASE_URL}/api/capture/assets/{a.pk}"
        for a in capture.assets.filter(kind="photo")
    ]
    public_keys = [
        "subdivision",
        "maintenance",
        "no_maintenance",
        "half_bathrooms",
        "land_m2",
        "age_type",
        "age_years",
        "condition",
        "storage_rooms",
        "elevators",
        "floors",
        "amenities",
        "videos",
        "tours",
    ]
    prop.details = {key: capture.data.get(key) for key in public_keys}
    prop.details["plans"] = [
        f"/api/capture/assets/{a.pk}" for a in capture.assets.filter(kind="plan")
    ]
    prop.full_clean()
    prop.save()
    capture.property = prop


def unpublish(capture):
    from datalayer.inventory import notify_unpublished

    if capture.property_id:
        prop = Property.objects.select_for_update().get(pk=capture.property_id)
        was = prop.published
        prop.published = False
        prop.save(update_fields=["published", "updated_at"])
        notify_unpublished(prop, was)


@transaction.atomic
def review(capture_id, actor, payload):
    capture = (
        Capture.objects.select_for_update(of=("self",))
        .select_related("owner", "advisor")
        .get(pk=capture_id)
    )
    check_revision(capture, payload.get("revision"))
    action = payload.get("action")
    if capture.status == "draft":
        raise ValueError("La solicitud todavía es un borrador del propietario.")
    if action == "retry_delivery":
        row = capture.deliveries.select_for_update().get(pk=payload.get("delivery_id"))
        if not can_retry(row):
            raise ValueError(
                "Este aviso no admite reenvío. Revisa su resultado y la configuración de correo."
            )
        if (
            row.channel == "email"
            and row.attachment.get("kind") == "capture_contract"
            and not approval_matches(capture, row.attachment)
        ):
            raise ValueError("La aprobación cambió. No se reenviará un contrato anterior.")
        from worker.tasks import deliver_capture_message

        row.recipient = (
            capture.owner.email
            if row.channel == "email"
            else capture.advisor.telegram_chat_id
            if capture.advisor
            else ""
        )
        row.status = "pending"
        row.error_code = ""
        row.save()
        deliver_capture_message.defer(delivery_id=row.pk)
        event(capture, actor, "retry_delivery", f"Aviso {row.pk}")
        return capture
    if action == "update":
        from datalayer.google_locations import validate_reference

        data = CaptureData.model_validate(payload.get("data", capture.data))
        data.check_complete()
        validate_reference(capture.owner, data.model_dump(mode="json"), complete=True)
        unpublish(capture)
        capture.agreements.filter(ended_at__isnull=True).update(ended_at=timezone.now())
        capture.data = data.model_dump(mode="json")
        capture.status = "submitted"
        capture.verified_at = None
        capture.pending_request = {}
    elif action == "approve":
        if capture.status not in {"submitted", "rejected", "expired", "withdrawn"}:
            raise ValueError("La solicitud no está pendiente de aprobación.")
        data = check_complete(capture)
        if payload.get("representation_verified") is not True:
            raise CaptureError(
                "Confirma que verificaste al propietario o representante.",
                code="representation_verification_required",
                field="representation_verified",
            )
        outside = (
            data.state != "Jalisco" or normalize_zone(data.municipality) not in BASE_MUNICIPALITIES
        )
        if outside and payload.get("outside_area_approved") is not True:
            raise CaptureError(
                "Aprueba expresamente la captación fuera de la zona base.",
                code="outside_area_approval_required",
                field="outside_area_approved",
            )
        capture.outside_area_approved = outside
        capture.exact_location_approved = payload.get("exact_location_approved") is True
        capture.reviewed_by = actor
        capture.verified_at = timezone.now()
        capture.status = "approved"
        sync_property(capture)
    elif action in {"withdraw", "reject", "renew"}:
        if action == "renew" and not capture.verified_at:
            raise ValueError("Primero revisa el inmueble y su representación.")
        unpublish(capture)
        capture.agreements.filter(ended_at__isnull=True).update(ended_at=timezone.now())
        capture.status = {"withdraw": "withdrawn", "reject": "rejected", "renew": "approved"}[
            action
        ]
        capture.pending_request = {}
    elif action == "publish":
        from datalayer.inventory import set_publication

        set_publication(capture.property_id, True)
        capture.status = "published"
    elif action == "resolve_request":
        capture.pending_request = {}
    elif action != "valuation":
        raise ValueError("Acción inválida")
    if "advisor_id" in payload:
        capture.advisor = Advisor.objects.get(pk=payload["advisor_id"])
        if capture.property_id:
            Property.objects.filter(pk=capture.property_id).update(advisor=capture.advisor)
    if "review_notes" in payload:
        capture.review_notes = str(payload["review_notes"])[:5000]
    if action == "valuation":
        from decimal import Decimal, InvalidOperation

        try:
            value = Decimal(str(payload.get("valuation", "")))
            if not value.is_finite() or value <= 0 or value > 999999999999:
                raise ValueError("Importe inválido")
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Indica una opinión de valor válida.") from exc
        capture.valuation = str(value)
        capture.valuation_notes = str(payload.get("valuation_notes", ""))[:5000]
        capture.valuation_communicated_at = (
            timezone.now() if payload.get("communicated") is True else None
        )
    capture.revision += 1
    capture.save()
    event(capture, actor, action, str(payload.get("summary", "")))
    if action in {"approve", "renew"}:
        request_acceptance(capture)
    return capture


@transaction.atomic
def accept(capture_id, owner, revision, version):
    capture = Capture.objects.select_for_update().get(pk=capture_id, owner=owner)
    if active_agreement(capture) and capture.status in {"accepted", "published"}:
        return capture
    check_revision(capture, revision)
    if (
        capture.status != "approved"
        or not capture.verified_at
        or version != CONTRACT_VERSION
        or not owner.email_verified_at
    ):
        raise ValueError("La solicitud debe estar aprobada y el contrato vigente antes de aceptar.")
    now = timezone.localtime(timezone.now())
    month_index = now.year * 12 + now.month - 1 + 6
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    expires = now.replace(
        year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
    )
    capture.agreements.filter(ended_at__isnull=True).update(ended_at=now)
    CaptureAgreement.objects.create(
        capture=capture,
        version=version,
        text=CONTRACT_TEXT,
        snapshot=commercial_data(capture.data),
        accepted_by=owner,
        accepted_at=now,
        expires_at=expires,
    )
    capture.status = "accepted"
    capture.revision += 1
    capture.save()
    event(capture, owner, "accepted")
    notify(capture, "Exclusividad aceptada")
    return capture


@transaction.atomic
def owner_request(capture_id, owner, kind, message):
    if (
        kind not in {"change", "withdraw", "renew"}
        or not isinstance(message, str)
        or not message.strip()
        or len(message) > 1000
    ):
        raise ValueError("Indica el cambio, retirada o renovación que solicitas.")
    capture = Capture.objects.select_for_update().get(pk=capture_id, owner=owner)
    if capture.status == "draft":
        raise ValueError("Todavía puedes editar tu borrador.")
    if capture.pending_request:
        raise ValueError("Ya existe una solicitud pendiente. El asesor debe resolverla.")
    capture.pending_request = {
        "kind": kind,
        "message": message.strip(),
        "created_at": timezone.now().isoformat(),
    }
    capture.revision += 1
    capture.save()
    event(capture, owner, kind, message)
    notify(capture, "Solicitud del propietario")
    return capture


@transaction.atomic
def expire(capture_id):
    capture = Capture.objects.select_for_update().get(pk=capture_id)
    if capture.status not in {"accepted", "published"} or active_agreement(capture):
        return
    unpublish(capture)
    capture.agreements.filter(ended_at__isnull=True).update(ended_at=timezone.now())
    capture.status = "expired"
    capture.revision += 1
    capture.save()
    event(capture, None, "expired")
    notify(capture, "Exclusividad vencida")
