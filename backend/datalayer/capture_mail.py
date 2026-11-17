"""Mail configuration, signed delivery facts and safe retry eligibility. No network I/O."""

from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from datalayer.models import CaptureDelivery, CaptureMailEvent

EVENT_STATUS = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.failed": "failed",
    "email.suppressed": "suppressed",
}
TERMINAL = {"bounced", "complained", "suppressed"}


def configuration():
    provider = settings.CAPTURE_EMAIL_PROVIDER
    issues = []
    local = provider == "django" and settings.EMAIL_BACKEND in {
        "django.core.mail.backends.filebased.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
    if provider not in {"django", "resend"}:
        issues.append("El proveedor de correo no es válido.")
    if provider == "resend" and not settings.RESEND_API_KEY:
        issues.append("Falta configurar la clave de Resend en el servidor.")
    if not local:
        address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        try:
            validate_email(address)
            if address.rsplit("@", 1)[-1] in {"localhost", "example.com", "example.invalid"}:
                raise ValidationError("Remitente de ejemplo")
        except ValidationError:
            issues.append("Falta configurar un remitente del dominio verificado.")
        if (
            provider == "django"
            and settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        ):
            if settings.EMAIL_HOST in {"", "localhost"}:
                issues.append("Falta configurar el servidor SMTP.")
    return {
        "provider": "local" if local else provider,
        "ready": not local and not issues,
        "local": local,
        "issues": issues,
        "webhook_ready": provider == "resend" and bool(settings.RESEND_WEBHOOK_SECRET),
    }


def can_retry(row):
    if row.channel == "email" and row.status == "stored":
        return configuration()["ready"]
    return row.status in {"failed", "blocked"} and not (
        row.channel == "email" and row.error_code.startswith("webhook_")
    )


@transaction.atomic
def apply_events(delivery_id):
    row = CaptureDelivery.objects.select_for_update().get(pk=delivery_id)
    if row.provider != "resend" or not row.provider_id:
        return
    # Recompute from immutable facts, so callback order cannot regress a delivery.
    events = list(
        CaptureMailEvent.objects.filter(provider_id=row.provider_id).order_by("occurred_at", "pk")
    )
    if not events:
        return
    status = "sent"
    for event in events:
        candidate = EVENT_STATUS[event.event_type]
        if status in TERMINAL:
            if candidate == "complained":
                status = candidate
            continue
        if status == "delivered" and candidate in {"sent", "delayed"}:
            continue
        status = candidate
    row.status = status
    row.error_code = "webhook_" + status if status in TERMINAL | {"failed"} else ""
    row.save(update_fields=["status", "error_code", "updated_at"])


@transaction.atomic
def store_event(event_id, provider_id, event_type, occurred_at, delivery_tag=None):
    _, created = CaptureMailEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"provider_id": provider_id, "event_type": event_type, "occurred_at": occurred_at},
    )
    if created:
        # A signed callback can beat the HTTP receipt or recover a worker crash.
        if (
            isinstance(delivery_tag, str)
            and delivery_tag.isascii()
            and delivery_tag.isdigit()
            and len(delivery_tag) < 19
        ):
            row = (
                CaptureDelivery.objects.select_for_update()
                .filter(
                    pk=int(delivery_tag),
                    provider="resend",
                    provider_id="",
                    status__in=["sending", "uncertain"],
                )
                .first()
            )
            if row:
                row.provider_id = provider_id
                row.save(update_fields=["provider_id"])
        for pk in CaptureDelivery.objects.filter(
            provider="resend", provider_id=provider_id
        ).values_list("pk", flat=True):
            apply_events(pk)
