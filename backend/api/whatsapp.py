"""Meta verification and signed webhook ingestion, independent of browser sessions."""

import hashlib
import hmac
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from datalayer.whatsapp import store_events


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        token = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        if (
            token
            and request.GET.get("hub.mode") == "subscribe"
            and hmac.compare_digest(request.GET.get("hub.verify_token", ""), token)
        ):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse(status=403)
    secret = settings.META_APP_SECRET
    if not secret or len(request.body) > 1_000_000:
        return HttpResponse(status=403)
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            return HttpResponse(status=400)
        store_events(payload)
    except (ValueError, TypeError, KeyError, AttributeError):
        return HttpResponse(status=400)
    return JsonResponse({"ok": True})
