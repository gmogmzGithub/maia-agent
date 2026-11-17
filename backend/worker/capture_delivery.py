"""Durable capture notifications, never retrying uncertain sends automatically."""

import logging

import httpx
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import transaction

from datalayer.capture_approval import approval_matches
from datalayer.capture_mail import apply_events, configuration
from datalayer.models import CaptureDelivery
from worker.capture_email import email_html, send_resend

logger = logging.getLogger(__name__)


def deliver(delivery_id, client=None):
    with transaction.atomic():
        row = (
            CaptureDelivery.objects.select_for_update(of=("self",))
            .select_related("capture")
            .get(pk=delivery_id)
        )
        if row.status != "pending":
            return
        if row.attachment.get("kind") == "capture_contract":
            capture = row.capture
            if not approval_matches(capture, row.attachment):
                row.status, row.error_code = "superseded", "approval_no_longer_current"
                row.save()
                return
        if not row.recipient or (row.channel == "telegram" and not settings.TELEGRAM_BOT_TOKEN):
            row.status, row.error_code = "blocked", "recipient_or_provider_missing"
            row.save()
            return
        if row.channel == "email":
            config = configuration()
            if not config["local"] and not config["ready"]:
                row.status, row.error_code = "blocked", "email_configuration_missing"
                row.save()
                return
            row.provider = "resend" if settings.CAPTURE_EMAIL_PROVIDER == "resend" else "django"
            row.provider_id = ""
            row.attempts += 1
        row.status = "sending"
        row.save()
    status, error = "uncertain", "send_result_unknown"
    provider_id = ""
    try:
        if row.channel == "email":
            pdf = None
            if row.attachment.get("kind") == "capture_contract":
                from datalayer.capture_contract import contract_pdf

                try:
                    pdf = contract_pdf(row.attachment)
                except Exception:
                    CaptureDelivery.objects.filter(pk=row.pk, status="sending").update(
                        status="failed", error_code="attachment_generation_failed"
                    )
                    return
            if settings.CAPTURE_EMAIL_PROVIDER == "resend":
                result = send_resend(row, pdf, client=client)
                status, error, provider_id = result.status, result.error, result.provider_id
            elif pdf is not None:
                message = EmailMultiAlternatives(
                    row.subject, row.body, settings.DEFAULT_FROM_EMAIL, [row.recipient]
                )
                message.attach("acuerdo-exclusividad.pdf", pdf, "application/pdf")
                message.attach_alternative(email_html(row), "text/html")
                sent = message.send()
            else:
                sent = send_mail(
                    row.subject,
                    row.body,
                    settings.DEFAULT_FROM_EMAIL,
                    [row.recipient],
                    html_message=email_html(row),
                )
            if settings.CAPTURE_EMAIL_PROVIDER != "resend":
                status, error = ("sent", "") if sent == 1 else ("failed", "mail_rejected")
            if (
                settings.CAPTURE_EMAIL_PROVIDER != "resend"
                and sent == 1
                and settings.EMAIL_BACKEND == "django.core.mail.backends.filebased.EmailBackend"
            ):
                status = "stored"
        else:
            with (
                httpx.Client(timeout=15, follow_redirects=False)
                if client is None
                else client as http
            ):
                base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
                check = http.post(base + "/getChat", json={"chat_id": row.recipient}).json()
                chat = check.get("result", {})
                if (
                    not check.get("ok")
                    or chat.get("type") != "private"
                    or str(chat.get("id")) != row.recipient
                ):
                    status, error = "failed", "private_chat_required"
                else:
                    response = http.post(
                        base + "/sendMessage",
                        json={
                            "chat_id": row.recipient,
                            "text": row.subject + "\n" + row.body,
                            "link_preview_options": {"is_disabled": True},
                        },
                    ).json()
                    if response.get("ok") and response.get("result", {}).get("message_id"):
                        status, error = "sent", ""
                    elif response.get("ok") is False and 400 <= response.get("error_code", 0) < 500:
                        status, error = "failed", "telegram_rejected"
    except httpx.ConnectError:
        status, error = "failed", "connection_failed"
    except Exception as exc:
        # Provider exceptions may contain credential-bearing URLs. Log only the type.
        error = type(exc).__name__[:80]
    CaptureDelivery.objects.filter(pk=row.pk, status="sending").update(
        status=status, error_code=error, provider_id=provider_id
    )
    if row.provider == "resend":
        apply_events(row.pk)
    logger.info("capture_delivery id=%s status=%s error=%s", row.pk, status, error)
