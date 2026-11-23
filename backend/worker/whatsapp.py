"""WhatsApp Cloud API transport. Durable sends, no blind retry after uncertainty."""

import logging
import re
from datetime import timedelta

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.models import FollowupAttempt, WhatsAppDelivery, WhatsAppTemplate
from datalayer.prospects import is_paused

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    pass


AUTH_ERRORS = {"whatsapp_token_expired", "whatsapp_auth_failed"}


def provider_error(response):
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    if error.get("code") == 190 and error.get("error_subcode") == 463:
        return "whatsapp_token_expired"
    if response.status_code == 401 or error.get("code") == 190:
        return "whatsapp_auth_failed"
    return "meta_http_" + str(response.status_code)


def check_credentials(client=None):
    """Read-only preflight, outside transactions, without logging provider bodies or tokens."""
    if not settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
        raise WhatsAppError("business_account_required")
    response = request(
        "GET",
        settings.WHATSAPP_BUSINESS_ACCOUNT_ID + "/message_templates?fields=name,status&limit=1",
        client=client,
    )
    if not response.is_success:
        raise WhatsAppError(provider_error(response))


def configured():
    return bool(
        settings.WHATSAPP_ACCESS_TOKEN
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and re.fullmatch(r"v[0-9]+\.0", settings.WHATSAPP_API_VERSION)
    )


def request(method, path, *, client=None, payload=None):
    from django.db import connection

    if connection.in_atomic_block:
        raise RuntimeError("whatsapp_http_inside_transaction")
    if not configured():
        raise WhatsAppError("whatsapp_not_configured")
    owned = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    try:
        return client.request(
            method,
            f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{path}",
            headers={"Authorization": "Bearer " + settings.WHATSAPP_ACCESS_TOKEN},
            json=payload,
            timeout=15,
        )
    finally:
        if owned:
            client.close()


def deliver(delivery_id, client=None):
    from datalayer.followups import due_date, eligible, snapshot, template_options
    from datalayer.whatsapp import canonical_number

    with transaction.atomic():
        item = (
            WhatsAppDelivery.objects.select_for_update()
            .select_related("conversation")
            .get(pk=delivery_id)
        )
        if item.status != "queued":
            return
        conversation = item.conversation
        attempt = (
            FollowupAttempt.objects.select_related("cycle__prospect", "cycle__conversation")
            .filter(delivery=item)
            .first()
        )
        reason = ""
        if attempt:
            reason = (
                "expired"
                if timezone.now() >= attempt.expires_at
                else eligible(attempt.cycle, timezone.now())
            )
            if due_date(attempt.cycle, attempt.day) != attempt.due_at:
                reason = "schedule_changed"
            if not reason and snapshot(attempt.cycle) != attempt.snapshot:
                reason = "context_changed"
            if not reason:
                template = item.payload.get("template", {})
                if not any(
                    o["name"] == template.get("name")
                    and o["language"] == template.get("language", {}).get("code")
                    and o["text"] == item.message.text
                    for o in template_options(attempt.cycle, attempt.day)
                ):
                    reason = "template_changed"
        elif is_paused(conversation) or (
            item.revision is not None and conversation.revision != item.revision
        ):
            reason = "conversation_changed"
        if item.payload.get("type") != "template" and (
            not conversation.last_whatsapp_at
            or conversation.last_whatsapp_at <= timezone.now() - timedelta(hours=24)
        ):
            reason = "outside_service_window"
        if reason:
            item.status, item.error_code = "skipped", reason
        elif not configured():
            item.status, item.error_code = "blocked", "whatsapp_not_configured"
        else:
            item.status, item.sent_at = "sending", timezone.now()
        item.save()
        if item.status != "sending":
            if attempt:
                attempt.status, attempt.reason = item.status, item.error_code
                attempt.save(update_fields=["status", "reason", "updated_at"])
            return
        payload = {
            "messaging_product": "whatsapp",
            "to": canonical_number(item.recipient),
            "biz_opaque_callback_data": str(item.pk),
            **item.payload,
        }
    # Final pre-transport check: never send text prepared from a now-private fact.
    if item.message.public_sources:
        from datalayer.public_history import message_projection

        if message_projection(item.message)["changed"]:
            with transaction.atomic():
                WhatsAppDelivery.objects.filter(pk=item.pk, status="sending").update(
                    status="skipped", error_code="property_facts_changed")
            return
    status, error, provider_id = "uncertain", "unknown_result", ""
    try:
        response = request(
            "POST", settings.WHATSAPP_PHONE_NUMBER_ID + "/messages", payload=payload, client=client
        )
        if 400 <= response.status_code < 500:
            status, error = "failed", provider_error(response)
        elif response.is_success:
            data = response.json()
            provider_id = str(data["messages"][0]["id"])
            if not provider_id or len(provider_id) > 256:
                raise ValueError("invalid_provider_id")
            status, error = "sent", ""
    except Exception:
        # The request may have been accepted. Never generate or send it again blindly.
        pass
    with transaction.atomic():
        item = WhatsAppDelivery.objects.select_for_update().get(pk=delivery_id)
        if item.status == "sending":
            item.status, item.error_code, item.provider_id = status, error, provider_id
            item.save()
        elif provider_id and not item.provider_id:
            item.provider_id = provider_id
            item.save(update_fields=["provider_id", "updated_at"])
        FollowupAttempt.objects.filter(delivery=item).update(
            status=item.status, reason=item.error_code, updated_at=timezone.now()
        )
        if attempt and item.error_code in AUTH_ERRORS:
            from datalayer.models import FollowupCycle

            FollowupCycle.objects.filter(pk=attempt.cycle_id, closed_at__isnull=True).update(
                suspended=True,
                reason=item.error_code,
            )
    logger.info(
        "whatsapp_send delivery=%s status=%s error=%s", delivery_id, item.status, item.error_code
    )


def recover():
    from datalayer.models import WhatsAppEvent
    from worker.dispatch import enqueue_followup, enqueue_whatsapp_delivery, enqueue_whatsapp_event

    now = timezone.now()
    WhatsAppDelivery.objects.filter(
        status="sending", sent_at__lt=now - timedelta(minutes=2)
    ).update(status="uncertain", error_code="process_interrupted", updated_at=now)
    FollowupAttempt.objects.filter(delivery__status="uncertain").update(
        status="uncertain", reason="unknown_delivery"
    )
    for item in WhatsAppDelivery.objects.filter(status="queued"):
        attempt = FollowupAttempt.objects.filter(delivery=item).first()
        if attempt:
            enqueue_followup(attempt.pk)
        else:
            enqueue_whatsapp_delivery(item.pk)
    for event_id in WhatsAppEvent.objects.filter(status="queued").values_list("pk", flat=True):
        enqueue_whatsapp_event(event_id)


def sync_templates(client=None):

    if not settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
        raise WhatsAppError("business_account_required")
    path = (
        settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        + "/message_templates?fields=name,language,status,components&limit=100"
    )
    rows = []
    for _ in range(20):
        response = request("GET", path, client=client)
        if not response.is_success:
            raise WhatsAppError("template_sync_failed")
        data = response.json()
        rows.extend(data.get("data", []))
        cursor = data.get("paging", {}).get("cursors", {}).get("after")
        if not data.get("paging", {}).get("next") or not cursor:
            break
        # Never follow a provider-supplied absolute URL containing credentials.
        from urllib.parse import quote

        path = (
            settings.WHATSAPP_BUSINESS_ACCOUNT_ID
            + "/message_templates?fields=name,language,status,components&limit=100&after="
            + quote(cursor, safe="")
        )
    else:
        raise WhatsAppError("template_catalog_too_large")
    with transaction.atomic():
        WhatsAppTemplate.objects.all().update(status="UNAVAILABLE")
        for row in rows:
            components = row.get("components", [])
            body = next((c.get("text", "") for c in components if c.get("type") == "BODY"), "")
            unsupported = any(c.get("type") != "BODY" for c in components)
            WhatsAppTemplate.objects.update_or_create(
                name=row["name"],
                language=row["language"],
                defaults={
                    "status": "UNSUPPORTED" if unsupported else row["status"],
                    "body": body,
                    "synced_at": timezone.now(),
                },
            )
    return len(rows)
