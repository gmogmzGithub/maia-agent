"""Staff-bound Google authorization; credentials never cross the API boundary."""

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import SessionAuthIsStaff

from datalayer.models import Advisor, CalendarAuthorization, CalendarConnection
from worker.google_calendar import (
    SCOPES,
    CalendarError,
    decrypt,
    encrypt,
    google_request,
    token_exchange,
)

router = Router(auth=SessionAuthIsStaff())


class AuthorizationConfirm(Schema):
    authorization_id: str


def session_hash(request):
    return hashlib.sha256((request.session.session_key or "").encode()).hexdigest()


def configured():
    return all(
        (
            settings.GOOGLE_CLIENT_ID,
            settings.GOOGLE_CLIENT_SECRET,
            settings.GOOGLE_REDIRECT_URI,
            settings.CALENDAR_ENCRYPTION_KEY,
        )
    )


def connection_output(advisor):
    conn = CalendarConnection.objects.filter(advisor=advisor).first()
    return {
        "advisor_id": advisor.pk,
        "configured": configured(),
        "connected": bool(conn and conn.connected),
        "email": conn.email if conn else "",
    }


@router.get("/crm/advisors/{advisor_id}/calendar", response=dict)
def calendar_connection(request, advisor_id: int):
    advisor = get_object_or_404(Advisor, pk=advisor_id)
    pending = (
        CalendarAuthorization.objects.filter(
            advisor=advisor,
            actor=request.user,
            session_hash=session_hash(request),
            consumed=False,
            created_at__gt=timezone.now() - timedelta(minutes=10),
        )
        .exclude(candidate="")
        .last()
    )
    return {
        **connection_output(advisor),
        "pending": {"id": str(pending.pk), "email": pending.email} if pending else None,
    }


@router.post("/crm/advisors/{advisor_id}/calendar/connect", response=dict)
def begin_connection(request, advisor_id: int):
    advisor = get_object_or_404(Advisor, pk=advisor_id)
    if not configured():
        raise HttpError(409, "Falta configurar Google Calendar en el backend y worker.")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    row = CalendarAuthorization.objects.create(
        advisor=advisor,
        actor=request.user,
        session_hash=session_hash(request),
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        verifier=encrypt({"value": verifier}),
    )
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent select_account",
        "state": str(row.pk) + "." + state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/calendar/callback", include_in_schema=False)
def callback(request, state: str = "", code: str = "", error: str = ""):
    try:
        row_id, secret = state.split(".", 1)
        with transaction.atomic():
            row = get_object_or_404(
                CalendarAuthorization.objects.select_for_update(),
                pk=row_id,
                actor=request.user,
                session_hash=session_hash(request),
                consumed=False,
                candidate="",
                created_at__gt=timezone.now() - timedelta(minutes=10),
            )
            if not secrets.compare_digest(
                row.state_hash, hashlib.sha256(secret.encode()).hexdigest()
            ):
                raise ValueError
            row.consumed = True
            row.save(update_fields=["consumed"])
        if error or not code:
            raise CalendarError("authorization_denied")
        token = token_exchange(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "code_verifier": decrypt(row.verifier)["value"],
            }
        )
        if not token.get("refresh_token") or not token.get("access_token"):
            raise CalendarError("offline_access_required")
        granted = set(token.get("scope", "").split())
        if not set(SCOPES[2:]).issubset(granted):
            raise CalendarError("calendar_scopes_missing")
        identity = google_request(
            "GET",
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": "Bearer " + token["access_token"]},
        )
        if (
            not identity.get("email_verified")
            or not identity.get("email")
            or not identity.get("sub")
        ):
            raise CalendarError("google_identity_unavailable")
        token["expires_at"] = timezone.now().timestamp() + token.get("expires_in", 3600)
        CalendarAuthorization.objects.filter(pk=row.pk).update(
            candidate=encrypt(token),
            email=identity["email"],
            subject=identity["sub"],
            verifier="",
            consumed=False,
        )
        return HttpResponseRedirect("/crm?calendar_advisor=" + str(row.advisor_id))
    except (ValueError, CalendarError):
        return HttpResponseRedirect("/crm?calendar_error=authorization_failed")


@router.post("/crm/advisors/{advisor_id}/calendar/confirm", response=dict)
def confirm_connection(request, advisor_id: int, data: AuthorizationConfirm):
    with transaction.atomic():
        advisor = get_object_or_404(Advisor.objects.select_for_update(), pk=advisor_id)
        row = get_object_or_404(
            CalendarAuthorization.objects.select_for_update(),
            pk=data.authorization_id,
            advisor=advisor,
            actor=request.user,
            session_hash=session_hash(request),
            consumed=False,
            created_at__gt=timezone.now() - timedelta(minutes=10),
        )
        if not row.candidate:
            raise HttpError(409, "Primero autoriza la cuenta de Google.")
        conn = CalendarConnection.objects.filter(advisor=advisor).first()
        if (
            conn
            and conn.subject != row.subject
            and conn.appointment_set.exclude(
                status__in=["cancelled", "done", "no_show", "failed"]
            ).exists()
        ):
            raise HttpError(409, "Resuelve las citas existentes antes de cambiar de cuenta Google.")
        if not conn:
            conn = CalendarConnection(advisor=advisor)
        elif conn.subject != row.subject:
            import uuid

            conn.generation = uuid.uuid4()
        conn.email, conn.subject, conn.credentials = row.email, row.subject, row.candidate
        conn.connected, conn.initiated_by = True, request.user
        conn.save()
        row.consumed, row.candidate = True, ""
        row.save(update_fields=["consumed", "candidate"])
    return connection_output(advisor)


@router.post("/crm/advisors/{advisor_id}/calendar/disconnect", response=dict)
def disconnect(request, advisor_id: int):
    advisor = get_object_or_404(Advisor, pk=advisor_id)
    CalendarConnection.objects.filter(advisor=advisor).update(connected=False, credentials="")
    CalendarAuthorization.objects.filter(advisor=advisor).update(
        consumed=True, candidate="", verifier=""
    )
    return connection_output(advisor)
