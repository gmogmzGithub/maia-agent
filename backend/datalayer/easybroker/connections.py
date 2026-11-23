"""Short configuration transactions, encrypted credentials and durable sync requests."""

import hashlib
import hmac
import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.closings import ClosingConflict, staff
from datalayer.easybroker.normalization import digest
from datalayer.easybroker.sync import invalidate, request_sync
from datalayer.models import (
    Advisor,
    EasyBrokerConnection,
    EasyBrokerRequest,
    User,
)


def cipher():
    try:
        return Fernet(settings.EASYBROKER_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise ValidationError(
            "Configura la clave de cifrado de EasyBroker en el servidor."
        ) from None


def fingerprint(key):
    # Independent encryption key also protects a fingerprint from offline guessing.
    cipher()
    return hmac.new(
        settings.EASYBROKER_ENCRYPTION_KEY.encode(), key.encode(), hashlib.sha256
    ).hexdigest()


def encrypt(key):
    if (
        not isinstance(key, str)
        or not key.strip()
        or len(key) > 1024
        or any(c.isspace() for c in key)
    ):
        raise ValidationError("Revisa la clave de EasyBroker.")
    return cipher().encrypt(key.encode()).decode()


def decrypt(connection):
    try:
        return cipher().decrypt(connection.encrypted_key.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise ValidationError("Reconecta la cuenta de EasyBroker.") from None


def authorize(actor, admin=False):
    staff(actor)
    current = User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    if admin and not current.is_superuser:
        raise PermissionDenied("Solo administradores pueden configurar conexiones.")
    return current


def replay(actor, request_id, resource, action, payload):
    request_id = uuid.UUID(str(request_id))
    signature = digest(payload)
    previous = EasyBrokerRequest.objects.filter(pk=request_id).first()
    if previous:
        if (previous.actor_id, previous.resource, previous.action, previous.signature) != (
            actor.pk,
            resource,
            action,
            signature,
        ):
            raise ClosingConflict("El identificador de solicitud ya se usó con otros datos.")
        return previous.result
    return None


def remember(actor, request_id, resource, action, payload, result):
    EasyBrokerRequest.objects.create(
        id=request_id,
        actor=actor,
        actor_email=actor.email,
        resource=resource,
        action=action,
        signature=digest(payload),
        result=result,
    )
    return result


def check_revision(row, revision):
    if row.revision != revision:
        raise ClosingConflict("El registro cambió. Actualiza antes de continuar.")


def connection_output(row):
    run = row.runs.order_by("-created_at").first()
    return {
        "id": str(row.pk),
        "name": row.name,
        "environment": row.environment,
        "advisor_id": row.advisor_id,
        "enabled": row.enabled,
        "revision": row.revision,
        "credential_configured": bool(row.encrypted_key),
        "error_code": row.error_code,
        "next_sync_at": row.next_sync_at.isoformat(),
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_run": run_output(run) if run else None,
    }


def run_output(row):
    return {
        "id": str(row.pk),
        "connection_id": str(row.connection_id),
        "status": row.status,
        "trigger": row.trigger,
        "initiator_email": row.initiator_email,
        "counters": row.counters,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@transaction.atomic
def create(actor, value):
    actor = authorize(actor, admin=True)
    payload = value.model_dump(mode="json", exclude={"key"})
    payload["credential"] = fingerprint(value.key)
    existing = replay(actor, value.request_id, "connections", "create", payload)
    if existing is not None:
        return existing
    Advisor.objects.get(pk=value.advisor_id)
    row = EasyBrokerConnection.objects.create(
        name=value.name,
        environment=value.environment,
        advisor_id=value.advisor_id,
        encrypted_key=encrypt(value.key),
        key_fingerprint=payload["credential"],
    )
    request_sync(row.pk, actor=actor)
    return remember(
        actor, value.request_id, "connections", "create", payload, connection_output(row)
    )


@transaction.atomic
def configure(actor, connection_id, value):
    actor = authorize(actor, admin=True)
    row = EasyBrokerConnection.objects.select_for_update().get(pk=connection_id)
    payload = value.model_dump(mode="json", exclude={"key"})
    if getattr(value, "key", None):
        payload["credential"] = fingerprint(value.key)
    existing = replay(actor, value.request_id, str(row.pk), value.action, payload)
    if existing is not None:
        return existing
    check_revision(row, value.revision)
    invalidate(row)
    if value.action == "configure":
        Advisor.objects.get(pk=value.advisor_id)
        row.name, row.advisor_id = value.name, value.advisor_id
    else:
        if value.action == "disconnect":
            row.enabled = False
        elif value.action == "reconnect":
            row.enabled = True
        elif value.action == "credential":
            row.encrypted_key = encrypt(value.key)
            row.key_fingerprint = fingerprint(value.key)
            row.continuity_verified = not row.listings.exists()
            row.error_code = "continuity_pending" if not row.continuity_verified else ""
        from datalayer.easybroker.imports import block_connection

        block_connection(row, actor=actor)
    row.revision += 1
    row.next_sync_at = timezone.now()
    row.save()
    if row.enabled:
        request_sync(row.pk, actor=actor)
    return remember(
        actor, value.request_id, str(row.pk), value.action, payload, connection_output(row)
    )


@transaction.atomic
def manual_sync(actor, connection_id, value):
    actor = authorize(actor)
    row = EasyBrokerConnection.objects.select_for_update().get(pk=connection_id)
    payload = value.model_dump(mode="json")
    existing = replay(actor, value.request_id, str(row.pk), "sync", payload)
    if existing is not None:
        return existing
    check_revision(row, value.revision)
    result = run_output(request_sync(row.pk, actor=actor))
    return remember(actor, value.request_id, str(row.pk), "sync", payload, result)
