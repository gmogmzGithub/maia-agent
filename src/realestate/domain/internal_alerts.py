"""Durable operational notices to the operation's own people.

Deliberately *not* the Outbox. ADR-0045 gates every message to a Contact on
consent, suppression and the 24-hour service window; these go to members of the
Brokerage Organization on a private channel it opened itself, where those
concepts are meaningless. Telling an Advisor that somebody is waiting is not
outreach.

What the two paths do share is durability, and that is the reason this module
exists rather than a direct Telegram call at each site. The row is written in
the transaction that caused it, and delivery is a separate claimable step. That
is what makes the 15-minute human-handoff escalation exactly-once across a
restart: the escalation stamp and the alert row commit together, so a process
that dies before delivering re-derives the same pending alert instead of
alerting twice or not at all.

Two properties are chosen deliberately and differ from the Lead-facing rules:

* **at-least-once, not at-most-once.** ``dedupe_key`` makes creation
  idempotent, and a crash between the Telegram send and the stamp can repeat one
  internal notice. For an operator's alert a duplicate beats a miss; P-036 makes
  the opposite trade for a Contact, where a duplicate is worse than silence.
* **undeliverable is not lost.** A recipient with no configured chat produces an
  ``Undeliverable`` alert that stays visible in the CRM, and the
  Administrators are told the immediate notice could not be delivered. Nothing
  fails silently because a configuration value is absent.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    InternalAlert,
    InternalAlertKind,
    InternalAlertStatus,
    MemberRole,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor

logger = logging.getLogger(__name__)

#: How long a claimed-but-undelivered alert may sit before another worker may
#: take it. Short: the whole point of an immediate alert is immediacy.
CLAIM_LEASE = timedelta(minutes=2)

ALERT_KIND_LABELS: dict[str, str] = {
    InternalAlertKind.HUMAN_HANDOFF_REQUESTED.value: "Un cliente pidió hablar con una persona",
    InternalAlertKind.HUMAN_HANDOFF_ESCALATED.value: "Solicitud de atención humana sin tomar",
    InternalAlertKind.APPOINTMENT_ADVISOR_REVIEW.value: "Una cita necesita revisión",
    InternalAlertKind.ABSENCE_REVIEW.value: "Cambio de equipo por revisar",
}

ALERT_STATUS_LABELS: dict[str, str] = {
    InternalAlertStatus.PENDING.value: "Por entregar",
    InternalAlertStatus.SENT.value: "Entregada",
    InternalAlertStatus.UNDELIVERABLE.value: "Sin canal configurado",
    InternalAlertStatus.FAILED.value: "Falló la entrega",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class ClaimedAlert:
    """One alert claimed for delivery, with where it is going.

    ``chat_ids`` is empty when there is nowhere to send it. The worker does not
    have to decide what that means: it reports the claim back and this module
    records ``Undeliverable``.
    """

    alert: InternalAlert
    chat_ids: tuple[str, ...]
    recipient_name: str | None


class InternalAlerts:
    """The internal notification module.

    Hides: idempotent creation, recipient resolution (one member, or every
    Administrator), claiming with a lease, the undeliverable outcome, and the
    audit trail for a raised alert.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def raise_alert(
        self,
        actor: Actor,
        *,
        kind: InternalAlertKind,
        subject_type: str,
        subject_id: str,
        title: str,
        body: str,
        dedupe_key: str,
        recipient_member_id: uuid.UUID | None,
    ) -> InternalAlert:
        """Record one notice. Never commits. Idempotent on ``dedupe_key``.

        Returning the existing row for a repeated key is what lets a caller
        stamp "already alerted" in the same transaction without checking first.
        """
        existing: InternalAlert | None = await self._session.scalar(
            select(InternalAlert)
            .where(InternalAlert.organization_id == actor.organization_id)
            .where(InternalAlert.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return existing

        alert = InternalAlert(
            organization_id=actor.organization_id,
            kind=kind.value,
            recipient_member_id=recipient_member_id,
            subject_type=subject_type,
            subject_id=subject_id,
            title=title[:200],
            body=body,
            dedupe_key=dedupe_key,
            status=InternalAlertStatus.PENDING.value,
        )
        self._session.add(alert)
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError:
            # Another transaction created the same key first. Its row is the
            # one that matters; this one never existed.
            found: InternalAlert | None = await self._session.scalar(
                select(InternalAlert)
                .where(InternalAlert.organization_id == actor.organization_id)
                .where(InternalAlert.dedupe_key == dedupe_key)
            )
            if found is None:  # pragma: no cover - the index is the only writer
                raise
            return found

        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="RaiseInternalAlert",
            subject_type=subject_type,
            subject_id=subject_id,
            details={
                "kind": kind.value,
                "recipient_member_id": (
                    str(recipient_member_id) if recipient_member_id else None
                ),
                "dedupe_key": dedupe_key,
            },
            commit=False,
        )
        logger.info("Raised internal alert %s for %s", kind.value, subject_id)
        return alert

    async def claim_due(self, limit: int = 20) -> list[ClaimedAlert]:
        """Claim pending alerts for delivery. Commits the claim.

        The lease is what stops two workers from sending the same notice while
        also stopping one crashed worker from parking it forever.
        """
        moment = _now()
        rows = list(
            await self._session.scalars(
                select(InternalAlert)
                .where(InternalAlert.status == InternalAlertStatus.PENDING.value)
                .where(
                    (InternalAlert.claimed_at.is_(None))
                    | (InternalAlert.claimed_at <= moment - CLAIM_LEASE)
                )
                .order_by(InternalAlert.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        claimed: list[ClaimedAlert] = []
        for row in rows:
            row.claimed_at = moment
            row.attempts += 1
            recipients = await self._recipients(row)
            claimed.append(
                ClaimedAlert(
                    alert=row,
                    chat_ids=tuple(chat for _, chat in recipients),
                    recipient_name=recipients[0][0] if len(recipients) == 1 else None,
                )
            )
        if rows:
            await self._session.commit()
        return claimed

    async def _recipients(self, alert: InternalAlert) -> list[tuple[str, str]]:
        """(display name, chat id) for everybody this alert is addressed to."""
        query = select(OrganizationMember).where(
            OrganizationMember.organization_id == alert.organization_id
        ).where(OrganizationMember.active.is_(True))
        if alert.recipient_member_id is not None:
            query = query.where(OrganizationMember.id == alert.recipient_member_id)
        else:
            query = query.where(
                OrganizationMember.role == MemberRole.ADMINISTRATOR.value
            )
        members = list(await self._session.scalars(query))
        return [
            (member.display_name, member.telegram_chat_id)
            for member in members
            if member.telegram_chat_id
        ]

    async def mark_sent(self, alert_id: uuid.UUID) -> None:
        row = await self._session.get(InternalAlert, alert_id)
        if row is None:
            return
        row.status = InternalAlertStatus.SENT.value
        row.delivered_at = _now()
        row.last_error = None
        await self._session.commit()

    async def mark_undeliverable(self, alert_id: uuid.UUID, detail: str) -> None:
        """No channel exists. The alert stays visible in the CRM regardless."""
        row = await self._session.get(InternalAlert, alert_id)
        if row is None:
            return
        row.status = InternalAlertStatus.UNDELIVERABLE.value
        row.last_error = detail
        await self._session.commit()
        logger.warning("Internal alert %s is undeliverable: %s", alert_id, detail)

    async def mark_failed(self, alert_id: uuid.UUID, detail: str) -> None:
        """Delivery failed. Left ``Pending`` while retries remain."""
        row = await self._session.get(InternalAlert, alert_id)
        if row is None:
            return
        row.last_error = detail
        if row.attempts >= 5:
            row.status = InternalAlertStatus.FAILED.value
        row.claimed_at = None
        await self._session.commit()

    # -- Reads -------------------------------------------------------------

    async def open_for(
        self, actor: Actor, *, limit: int = 20
    ) -> list[InternalAlert]:
        """Alerts this Actor should see, newest first.

        An Administrator sees the Organization's; an Advisor sees their own.
        Acknowledged alerts drop out, because an alert list nobody can empty
        stops being read.
        """
        query = (
            select(InternalAlert)
            .where(InternalAlert.organization_id == actor.organization_id)
            .where(InternalAlert.acknowledged_at.is_(None))
            .order_by(InternalAlert.created_at.desc())
            .limit(limit)
        )
        if not actor.sees_whole_operation:
            query = query.where(
                InternalAlert.recipient_member_id == actor.member_id
            )
        return list(await self._session.scalars(query))

    async def acknowledge(self, actor: Actor, alert_id: uuid.UUID) -> bool:
        """Dismiss one alert from the operator's list. Never commits."""
        row = await self._session.get(InternalAlert, alert_id)
        if row is None or row.organization_id != actor.organization_id:
            return False
        if not actor.sees_whole_operation and row.recipient_member_id != actor.member_id:
            return False
        if row.acknowledged_at is not None:
            return False
        row.acknowledged_at = _now()
        await self._session.flush()
        return True
