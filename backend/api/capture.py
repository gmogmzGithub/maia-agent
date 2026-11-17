"""Owner and staff transports. Public access never authorizes by phone or UUID alone."""

import hashlib
import json
import uuid
from datetime import timedelta
from functools import wraps
from io import BytesIO

from django.contrib.auth import authenticate, login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect
from pydantic import ValidationError as SchemaError

from datalayer import capture_assets, captures
from datalayer.capture_catalog import catalog
from datalayer.capture_errors import CaptureError
from datalayer.models import AccountThrottle, Capture, CaptureAsset, User
from datalayer.prospects import normalize_phone


def endpoint(fn):
    @wraps(fn)
    @csrf_protect
    def wrapped(request, *args, **kwargs):
        try:
            if request.method not in {"GET", "POST", "PUT", "DELETE"}:
                return JsonResponse({"detail": "Método no permitido"}, status=405)
            return fn(request, *args, **kwargs)
        except SchemaError as exc:
            errors = []
            for error in exc.errors(include_input=False, include_context=False):
                issue = {
                    "message": error["msg"].removeprefix("Value error, "),
                    "code": error["type"],
                }
                if error["loc"]:
                    issue["field"] = ".".join(str(part) for part in error["loc"])
                errors.append(issue)
            return JsonResponse({"detail": errors[0]["message"], "errors": errors}, status=422)
        except (ObjectDoesNotExist, Http404):
            return JsonResponse({"detail": "No encontramos esa solicitud o archivo."}, status=404)
        except ValidationError as exc:
            return JsonResponse({"detail": exc.messages[0]}, status=422)
        except signing.BadSignature:
            return JsonResponse(
                {"detail": "El enlace venció o no es válido. Solicita uno nuevo."}, status=422
            )
        except CaptureError as exc:
            issue = {"message": str(exc), "code": exc.code}
            if exc.field:
                issue["field"] = exc.field
            return JsonResponse({"detail": str(exc), "errors": [issue]}, status=422)
        except ValueError as exc:
            message = str(exc)
            return JsonResponse(
                {
                    "detail": message
                    if message and len(message) < 250
                    else "Revisa los datos para continuar."
                },
                status=422,
            )
        except (KeyError, TypeError):
            return JsonResponse(
                {"detail": "Revisa los datos o actualiza la página para continuar."}, status=422
            )
        except IntegrityError:
            return JsonResponse(
                {"detail": "La información cambió. Actualiza para continuar."}, status=409
            )

    return wrapped


def body(request):
    value = json.loads(request.body or b"{}")
    if not isinstance(value, dict):
        raise ValueError("Solicitud inválida")
    return value


def require_owner(request, verified=True):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Inicia sesión para continuar."}, status=401)
    if not request.user.phone:
        return JsonResponse({"detail": "Completa tu cuenta de propietario."}, status=403)
    if verified and not request.user.email_verified_at:
        return JsonResponse({"detail": "Verifica tu email para continuar."}, status=403)
    return None


def require_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"detail": "Se requiere acceso del equipo."}, status=403)
    return None


def account_output(user):
    return {"email": user.email, "phone": user.phone, "verified": bool(user.email_verified_at)}


@transaction.atomic
def throttle(request, action, limit=12):
    # Shared database limit works across backend processes; no raw IP is retained.
    key = hashlib.sha256(f"{action}:{request.META.get('REMOTE_ADDR', '')}".encode()).hexdigest()
    now = timezone.now()
    row, _ = AccountThrottle.objects.select_for_update().get_or_create(
        key=key, defaults={"started_at": now}
    )
    if row.started_at < now - timedelta(minutes=15):
        row.started_at, row.count = now, 0
    row.count += 1
    row.save()
    if row.count > limit:
        return JsonResponse(
            {"detail": "Espera unos minutos antes de volver a intentarlo."}, status=429
        )
    return None


def verification_mail(user):
    token = signing.dumps({"id": user.pk, "email": user.email}, salt="owner-email")
    from django.conf import settings

    captures.delivery(
        "email",
        f"verify:{user.pk}:{uuid.uuid4()}",
        user.email,
        "Verifica tu email en Maia",
        f"Confirma tu email para enviar tu propiedad:\n{settings.PUBLIC_BASE_URL}/propietarios#verify={token}\nEl enlace vence en 24 horas.",
    )


@endpoint
def account(request):
    if request.method == "GET":
        return JsonResponse(
            {
                "account": account_output(request.user)
                if request.user.is_authenticated and request.user.phone
                else None
            }
        )
    if request.method != "POST":
        return JsonResponse({}, status=405)
    payload = body(request)
    action = payload.get("action")
    blocked = throttle(request, str(action))
    if blocked:
        return blocked
    if action in {"register", "login", "reset_request"}:
        email = str(payload.get("email", "")).strip().casefold()
        validate_email(email)
        if len(email) > 254:
            raise ValueError("Email inválido")
    if action == "register":
        password = str(payload.get("password", ""))
        phone = normalize_phone(str(payload.get("phone", "")))
        if not phone:
            raise ValueError("Teléfono inválido")
        candidate = User(email=email, phone=phone)
        validate_password(password, candidate)
        if User.objects.filter(email=email).exists():
            return JsonResponse(
                {"detail": "Si ya tienes cuenta, inicia sesión o recupera tu contraseña."},
                status=409,
            )
        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password, phone=phone)
            verification_mail(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    elif action == "login":
        user = authenticate(request, username=email, password=str(payload.get("password", "")))
        if user is None or not user.phone:
            return JsonResponse({"detail": "Email o contraseña incorrectos."}, status=401)
        login(request, user)
    elif action == "verify":
        value = signing.loads(payload.get("token", ""), salt="owner-email", max_age=86400)
        user = User.objects.filter(pk=value["id"], email=value["email"], is_active=True).first()
        if user is None:
            raise ValueError(
                "Este enlace corresponde a una cuenta que ya no existe. "
                "Solicita un nuevo correo de verificación desde tu cuenta actual."
            )
        if not request.user.is_authenticated or request.user.pk != user.pk:
            return JsonResponse(
                {"detail": "Inicia sesión con la cuenta del enlace para verificarla."}, status=401
            )
        if not user.email_verified_at:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
    elif action == "resend":
        denied = require_owner(request, verified=False)
        if denied:
            return denied
        user = request.user
        if not user.email_verified_at:
            verification_mail(user)
    elif action == "reset_request":
        user = User.objects.filter(email=email, is_active=True).exclude(phone="").first()
        if user:
            from django.conf import settings

            uid = urlsafe_base64_encode(str(user.pk).encode())
            token = default_token_generator.make_token(user)
            captures.delivery(
                "email",
                f"reset:{user.pk}:{uuid.uuid4()}",
                user.email,
                "Recupera tu acceso a Maia",
                f"Crea una nueva contraseña:\n{settings.PUBLIC_BASE_URL}/propietarios#reset={uid}:{token}",
            )
        return JsonResponse({"detail": "Si existe una cuenta con ese email, recibirás un enlace."})
    elif action == "reset":
        uid, token = str(payload.get("token", "")).split(":", 1)
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
        if not user.phone or not default_token_generator.check_token(user, token):
            raise ValueError("Enlace inválido")
        password = str(payload.get("password", ""))
        validate_password(password, user)
        user.set_password(password)
        user.save(update_fields=["password"])
        return JsonResponse({"detail": "Contraseña actualizada. Inicia sesión."})
    else:
        raise ValueError("Acción inválida")
    return JsonResponse({"account": account_output(user), "csrf_token": get_token(request)})


@endpoint
def options(request):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    return JsonResponse(catalog())


@endpoint
def contract_document(request, capture_id):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    capture = Capture.objects.get(pk=capture_id)
    if not request.user.is_authenticated or (
        not request.user.is_staff
        and (request.user.pk != capture.owner_id or not request.user.email_verified_at)
    ):
        raise Http404
    from datalayer.capture_contract import contract_pdf, contract_snapshot

    agreement = (
        None
        if capture.status == "approved"
        else capture.agreements.order_by("-accepted_at").first()
    )
    if capture.status != "approved" and not agreement:
        raise Http404
    response = FileResponse(
        BytesIO(contract_pdf(contract_snapshot(capture, agreement))),
        content_type="application/pdf",
        as_attachment=True,
        filename="acuerdo-exclusividad.pdf",
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@endpoint
def listing(request):
    denied = require_owner(request)
    if denied:
        return denied
    if request.method == "GET":
        return JsonResponse(
            {
                "captures": [
                    captures.output(c) for c in request.user.captures.order_by("-updated_at")
                ]
            }
        )
    if request.method == "POST":
        blocked = throttle(request, "draft", 60)
        if blocked:
            return blocked
        payload = body(request)
        capture_id = uuid.UUID(str(payload["id"]))
        capture = captures.save_draft(
            request.user, payload["data"], capture_id, payload.get("revision")
        )
        return JsonResponse(captures.output(capture))
    return JsonResponse({}, status=405)


@endpoint
def detail(request, capture_id):
    denied = require_owner(request)
    if denied:
        return denied
    capture = Capture.objects.get(pk=capture_id, owner=request.user)
    if request.method == "GET":
        return JsonResponse(captures.output(capture))
    if request.method != "POST":
        return JsonResponse({}, status=405)
    payload = body(request)
    action = payload.get("action")
    if action == "submit":
        capture = captures.submit(capture_id, request.user, payload.get("revision"))
    elif action == "accept":
        if payload.get("accepted") is not True:
            raise ValueError("Confirma la aceptación")
        capture = captures.accept(
            capture_id, request.user, payload.get("revision"), payload.get("version")
        )
    elif action == "request":
        capture = captures.owner_request(
            capture_id, request.user, payload.get("kind"), payload.get("message")
        )
    elif action == "rotate":
        capture = capture_assets.rotate(
            request.user, capture_id, payload["asset_id"], payload.get("revision")
        )
    elif action == "reorder":
        capture = capture_assets.reorder(
            request.user, capture_id, payload["ids"], payload.get("revision")
        )
    else:
        raise ValueError("Acción inválida")
    return JsonResponse(captures.output(capture))


@endpoint
def upload(request, capture_id):
    denied = require_owner(request)
    if denied:
        return denied
    if request.method != "POST":
        return JsonResponse({}, status=405)
    capture = capture_assets.upload(
        request.user,
        capture_id,
        request.POST.get("kind"),
        uuid.UUID(request.POST.get("request_id", "")),
        request.FILES["file"],
    )
    return JsonResponse(captures.output(capture))


@endpoint
def asset(request, asset_id):
    row = CaptureAsset.objects.select_related("capture__property").get(pk=asset_id)
    capture = row.capture
    private_access = request.user.is_authenticated and (
        (request.user.pk == capture.owner_id and request.user.email_verified_at)
        or request.user.is_staff
    )
    public_access = (
        capture.property_id and capture.property.published and captures.active_agreement(capture)
    )
    if request.method == "GET":
        if not private_access and not public_access:
            raise Http404
        response = FileResponse(
            row.file.open("rb"),
            content_type=row.content_type,
            as_attachment=row.content_type == "application/pdf",
            filename="plano.pdf" if row.content_type == "application/pdf" else "imagen.webp",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
    if request.method == "DELETE":
        denied = require_owner(request)
        if denied:
            return denied
        capture = capture_assets.delete(request.user, asset_id)
        return JsonResponse(captures.output(capture))
    return JsonResponse({}, status=405)


@endpoint
def crm_list(request):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method != "GET":
        return JsonResponse({}, status=405)
    return JsonResponse(
        {
            "captures": [
                captures.output(c, staff=True)
                for c in Capture.objects.exclude(status="draft")
                .select_related("owner", "advisor")
                .order_by("-updated_at")
            ]
        }
    )


@endpoint
def crm_detail(request, capture_id):
    denied = require_staff(request)
    if denied:
        return denied
    if request.method == "GET":
        return JsonResponse(captures.output(Capture.objects.get(pk=capture_id), staff=True))
    if request.method != "POST":
        return JsonResponse({}, status=405)
    capture = captures.review(capture_id, request.user, body(request))
    return JsonResponse(captures.output(capture, staff=True))
