import json
import uuid

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from ninja.security import APIKeyCookie


def browser_id(request):
    if "browser_id" not in request.session:
        request.session["browser_id"] = str(uuid.uuid4())
    return request.session["browser_id"]


class BrowserAuth(APIKeyCookie):
    param_name = settings.SESSION_COOKIE_NAME

    def authenticate(self, request, key):
        return request.session.get("browser_id") if key else None


@require_GET
def session_view(request):
    browser_id(request)
    return JsonResponse(
        {
            "csrf_token": get_token(request),
            "staff": request.user.is_authenticated and request.user.is_staff,
            "email": request.user.email if request.user.is_authenticated else None,
            "ai_configured": bool(settings.ANTHROPIC_API_KEY),
        }
    )


@require_POST
@csrf_protect
def login_view(request):
    try:
        data = json.loads(request.body)
        email = str(data.get("email", "")).strip().casefold()
        password = str(data.get("password", ""))
    except (ValueError, AttributeError):
        return JsonResponse({"detail": "Solicitud inválida"}, status=400)
    user = authenticate(request, username=email, password=password)
    if user is None or not user.is_staff:
        return JsonResponse({"detail": "Email o contraseña incorrectos"}, status=401)
    login(request, user)
    browser_id(request)
    return JsonResponse({"email": user.email, "csrf_token": get_token(request)})


@require_POST
@csrf_protect
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})
