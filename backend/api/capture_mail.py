"""Signed Resend events; browser sessions never authorize a delivery callback."""

import base64
import hashlib
import hmac
import json
import time

from django.conf import settings
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from datalayer.capture_mail import EVENT_STATUS, store_event


def verified(raw, headers):
    try:
        secret = settings.RESEND_WEBHOOK_SECRET
        if not secret.startswith("whsec_"):
            return False
        key = base64.b64decode(secret[6:], validate=True)
        event_id, stamp = headers.get("svix-id", ""), headers.get("svix-timestamp", "")
        if not key or not 1 <= len(event_id) <= 200 or abs(time.time() - int(stamp)) > 300:
            return False
        content = f"{event_id}.{stamp}.".encode() + raw
        expected = base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode()
        return any(
            hmac.compare_digest(value[3:], expected)
            for value in headers.get("svix-signature", "")[:2048].split()
            if value.startswith("v1,")
        )
    except (ValueError, TypeError):
        return False


@csrf_exempt
@require_POST
def webhook(request):
    if len(request.body) > 100_000 or not verified(request.body, request.headers):
        return JsonResponse({"detail": "Firma inválida."}, status=403)
    try:
        payload = json.loads(request.body)
        kind = payload["type"]
        if kind not in EVENT_STATUS:
            return JsonResponse({"ok": True})
        provider_id = payload["data"]["email_id"]
        occurred_at = parse_datetime(payload["created_at"])
        if (
            not isinstance(provider_id, str)
            or not 1 <= len(provider_id) <= 128
            or occurred_at is None
            or is_naive(occurred_at)
        ):
            raise ValueError("Evento inválido")
        tags = payload["data"].get("tags", {})
        store_event(
            request.headers["svix-id"],
            provider_id,
            kind,
            occurred_at,
            tags.get("capture_delivery") if isinstance(tags, dict) else None,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return JsonResponse({"detail": "Evento inválido."}, status=400)
    return JsonResponse({"ok": True})
