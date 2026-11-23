"""Own the durable sync protocol; workers exchange one batch result at a time."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.models import AccountThrottle, EasyBrokerConnection, EasyBrokerSyncRun


class StaleRun(Exception):
    pass


class BatchError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Batch:
    connection: EasyBrokerConnection
    kind: str
    target: str | int | None
    _run_id: uuid.UUID
    _lease: uuid.UUID


def fenced(run_id, lease):
    # Always lock connection -> run -> listing -> offer -> policy.
    connection_id = EasyBrokerSyncRun.objects.values_list("connection_id", flat=True).get(pk=run_id)
    connection = EasyBrokerConnection.objects.select_for_update().get(pk=connection_id)
    run = EasyBrokerSyncRun.objects.select_for_update().get(pk=run_id)
    if (
        not connection.enabled
        or connection.generation != run.generation
        or run.status != "running"
        or run.lease != lease
        or not run.lease_until
        or run.lease_until <= timezone.now()
    ):
        raise StaleRun
    return connection, run


def invalidate(connection):
    """The caller holds the connection lock and persists its configuration."""
    connection.generation += 1
    connection.runs.filter(status__in=["queued", "running"]).update(
        status="superseded", finished_at=timezone.now()
    )


@transaction.atomic
def request_sync(connection_id, *, actor=None):
    from worker.dispatch import enqueue_easybroker

    row = EasyBrokerConnection.objects.select_for_update().get(pk=connection_id)
    if not row.enabled:
        raise ValidationError("La conexión está desconectada.")
    active = row.runs.filter(status__in=["queued", "running"]).first()
    if active:
        return active
    run = EasyBrokerSyncRun.objects.create(
        connection=row,
        generation=row.generation,
        initiator=actor,
        initiator_email=actor.email if actor else "",
        trigger="manual" if actor else "hourly",
        checkpoint={"page": 1, "pending": [], "seen": [], "next_page": 1, "attempts": 0},
    )
    row.next_sync_at = timezone.now() + timedelta(hours=1, seconds=row.pk.int % 60)
    row.save(update_fields=["next_sync_at"])
    enqueue_easybroker(run.pk)
    return run


@transaction.atomic
def claim(run_id):
    from worker.dispatch import enqueue_easybroker

    connection_id = EasyBrokerSyncRun.objects.values_list("connection_id", flat=True).get(pk=run_id)
    connection = EasyBrokerConnection.objects.select_for_update().get(pk=connection_id)
    run = EasyBrokerSyncRun.objects.select_for_update().get(pk=run_id)
    now = timezone.now()
    if run.status not in {"queued", "running"}:
        return None
    if not connection.enabled or connection.generation != run.generation:
        run.status, run.finished_at = "superseded", now
        run.save()
        return None
    if run.lease_until and run.lease_until > now:
        return None
    throttle, _ = AccountThrottle.objects.select_for_update().get_or_create(
        key="easybroker-global", defaults={"started_at": now}
    )
    if throttle.started_at > now:
        enqueue_easybroker(run.pk, at=throttle.started_at)
        return None
    throttle.started_at = now + timedelta(seconds=0.5)
    throttle.save(update_fields=["started_at"])
    run.status, run.lease, run.lease_until = "running", uuid.uuid4(), now + timedelta(seconds=15)
    run.save()
    state = run.checkpoint
    if not connection.continuity_verified:
        known = connection.listings.filter(revision__gt=0).order_by("pk").first()
        kind, target = "continuity", known.public_id if known else None
    elif state.get("pending"):
        item = state["pending"][0]
        kind, target = (
            ("detail", item["public_id"])
            if item["status"] == "published"
            else ("observation", None)
        )
    elif state.get("next_page") is not None:
        kind, target = "statuses", state["next_page"]
    else:
        kind, target = "finish", None
    return Batch(connection, kind, target, run.pk, run.lease)


def _checkpoint(connection, run, state, *, error="", done=False, retry_after=0):
    from worker.dispatch import enqueue_easybroker

    run.checkpoint = state
    run.counters = {
        "seen": len(state.get("seen", [])),
        "checked": state.get("checked", 0),
        "failed": state.get("failed", 0),
    }
    run.lease_until, run.lease = None, None
    run.error_code = error or run.error_code
    if error:
        connection.error_code = error
    if done:
        run.status = "partial" if state.get("failed") else "complete"
        if error in {"authentication", "continuity_failed", "credential_unavailable"}:
            run.status = "failed"
        run.finished_at = timezone.now()
        if run.status == "complete":
            connection.last_success_at, connection.error_code = timezone.now(), ""
    run.save()
    connection.save(update_fields=["error_code", "last_success_at"])
    if not done:
        enqueue_easybroker(run.pk, at=timezone.now() + timedelta(seconds=max(0.5, retry_after)))


@transaction.atomic
def accept(batch, result):
    connection, run = fenced(batch._run_id, batch._lease)
    state = dict(run.checkpoint)
    if batch.kind == "continuity":
        if (
            not batch.target
            or not isinstance(result, dict)
            or result.get("public_id") != batch.target
        ):
            raise BatchError("continuity_failed")
        connection.error_code, connection.continuity_verified = "", True
        connection.save(update_fields=["error_code", "continuity_verified"])
    elif batch.kind in {"detail", "observation"}:
        from datalayer.easybroker.imports import observe

        observe(run.pk, run.lease, state["pending"][0], result)
        state["pending"] = state["pending"][1:]
        state["checked"] = state.get("checked", 0) + 1
    elif batch.kind == "statuses":
        items, next_page = result
        seen = set(state.get("seen", []))
        state["pending"] = []
        for item in items:
            if item["public_id"] not in seen:
                state["pending"].append(item)
                seen.add(item["public_id"])
        if items and not state["pending"] and next_page is not None:
            raise BatchError("repeated_page")
        state["seen"], state["next_page"] = sorted(seen), next_page
    state["attempts"] = 0
    _checkpoint(
        connection, run, state, done=not state.get("pending") and state.get("next_page") is None
    )


@transaction.atomic
def fail(batch, code, *, retry_after=15):
    connection, run = fenced(batch._run_id, batch._lease)
    if batch.kind == "continuity" and code == "not_found":
        code = "continuity_failed"
    state = dict(run.checkpoint)
    state["attempts"] = state.get("attempts", 0) + 1
    fatal = code in {"authentication", "continuity_failed", "credential_unavailable"}
    if fatal or state["attempts"] >= 3:
        state["failed"] = state.get("failed", 0) + 1
        if not fatal and state.get("pending"):
            state["pending"] = state["pending"][1:]
            state["attempts"] = 0
        else:
            state["pending"], state["next_page"] = [], None
    _checkpoint(
        connection,
        run,
        state,
        error=code,
        done=fatal or not state.get("pending") and state.get("next_page") is None,
        retry_after=retry_after,
    )


def maintain():
    from worker.dispatch import enqueue_easybroker

    now = timezone.now()
    for run in EasyBrokerSyncRun.objects.filter(status__in=["queued", "running"]):
        if not run.lease_until or run.lease_until <= now:
            enqueue_easybroker(run.pk)
    for row in EasyBrokerConnection.objects.filter(enabled=True, next_sync_at__lte=now).exclude(
        error_code__in=["authentication", "continuity_failed", "credential_unavailable"]
    ):
        request_sync(row.pk)
