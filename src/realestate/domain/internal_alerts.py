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
from datetime import timedelta

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
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor

logger = logging.getLogger(__name__)

#: How long a claimed-but-undelivered alert may sit before another worker may
#: take it. Short: the whole point of an immediate alert is immediacy.
#: Delivery attempts before an alert is abandoned as Failed. Named for the
#: same reason ``outbox.MAX_ATTEMPTS`` is: a bare 5 in a branch is not a
#: policy anyone can find.
MAX_ALERT_ATTEMPTS = 5

CLAIM_LEASE = timedelta(minutes=2)

ALERT_KIND_LABELS: dict[str, str] = {
    InternalAlertKind.HUMAN_HANDOFF_REQUESTED.value: "Un cliente pidió hablar con una persona",
    InternalAlertKind.HUMAN_HANDOFF_ESCALATED.value: "Solicitud de atención humana sin tomar",
    InternalAlertKind.APPOINTMENT_ADVISOR_REVIEW.value: "Una cita necesita revisión",
    InternalAlertKind.ABSENCE_REVIEW.value: "Cambio de equipo por revisar",
    InternalAlertKind.ALERT_UNDELIVERABLE.value: (
        "Una alerta interna no se pudo entregar"
    ),
}

ALERT_STATUS_LABELS: dict[str, str] = {
    InternalAlertStatus.PENDING.value: "Por entregar",
    InternalAlertStatus.SENT.value: "Entregada",
    InternalAlertStatus.UNDELIVERABLE.value: "Sin canal configurado",
    InternalAlertStatus.FAILED.value: "Falló la entrega",
}


@dataclass(frozen=True)
class ClaimedAlert:
    """One alert claimed for delivery, with where it is going.

    ``chat_ids`` is empty when there is nowhere to send it. The worker does not
    have to decide what that means: it reports the claim back and this module
    records ``Undeliverable``.
    """

    alert: InternalAlert
    chat_ids: tuple[str, ...]


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
            organization_id=actor.organization_id,
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

    async def claim_due(
        self,
        limit: int = 20,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> list[ClaimedAlert]:
        """Claim pending alerts for delivery. Commits the claim.

        The lease is what stops two workers from sending the same notice while
        also stopping one crashed worker from parking it forever.
        """
        moment = utc_now()
        query = (
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
        if organization_id is not None:
            query = query.where(InternalAlert.organization_id == organization_id)
        rows = list(
            await self._session.scalars(
                query
            )
        )
        # A broadcast alert addresses every Administrator, so a tick that claims
        # twenty of them would otherwise issue twenty identical queries.
        resolved: dict[tuple[uuid.UUID, uuid.UUID | None], list[tuple[str, str]]] = {}
        claimed: list[ClaimedAlert] = []
        for row in rows:
            row.claimed_at = moment
            row.attempts += 1
            audience = (row.organization_id, row.recipient_member_id)
            if audience not in resolved:
                resolved[audience] = await self._recipients(row)
            recipients = resolved[audience]
            claimed.append(
                ClaimedAlert(
                    alert=row,
                    chat_ids=tuple(chat for _, chat in recipients),
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
        await self._settle(
            alert_id, status=InternalAlertStatus.SENT, delivered=True
        )

    async def mark_undeliverable(self, alert_id: uuid.UUID, detail: str) -> None:
        """No channel exists. The alert stays visible in the CRM regardless.

        ADR-0049 asks for both halves: the row stays visible *and* "the
        Administrators are told the immediate notice could not be delivered".
        A missing configuration value must not make a customer's request for
        help disappear quietly into a warning nobody reads.

        A notice addressed to nobody in particular raises nothing further. An
        undeliverable broadcast means no Administrator has a channel at all, so
        there is nobody left to tell, and telling them about telling them would
        not terminate. The CRM row is the answer in that case.
        """
        row = await self._session.get(InternalAlert, alert_id)
        if row is None:
            return
        if (
            row.recipient_member_id is not None
            and row.kind != InternalAlertKind.ALERT_UNDELIVERABLE.value
        ):
            await self.raise_alert(
                Actor.product(row.organization_id, "InternalAlertDelivery"),
                kind=InternalAlertKind.ALERT_UNDELIVERABLE,
                subject_type="InternalAlert",
                subject_id=str(row.id),
                title="Una alerta interna no se pudo entregar",
                body=(
                    f"No se pudo entregar: {row.title}. {detail} "
                    "Configura el canal de alertas de la persona responsable "
                    "para que vuelva a recibir avisos."
                ),
                dedupe_key=f"alert-undeliverable:{row.id}",
                recipient_member_id=None,
            )
        if await self._settle(
            alert_id, status=InternalAlertStatus.UNDELIVERABLE, detail=detail
        ):
            logger.warning(
                "Internal alert %s is undeliverable: %s", alert_id, detail
            )

    async def mark_failed(self, alert_id: uuid.UUID, detail: str) -> None:
        """Delivery failed. Left ``Pending`` while retries remain."""
        await self._settle(alert_id, detail=detail, release_claim=True)

    async def _settle(
        self,
        alert_id: uuid.UUID,
        *,
        status: InternalAlertStatus | None = None,
        detail: str | None = None,
        delivered: bool = False,
        release_claim: bool = False,
    ) -> bool:
        """Record one delivery outcome and commit. False when the row is gone.

        The three outcomes differ only in which fields they set; the load, the
        missing-row answer and the commit are the same, and having written them
        three times is how the retry budget below ended up unnamed.
        """
        row = await self._session.get(InternalAlert, alert_id)
        if row is None:
            return False
        row.last_error = detail
        if delivered:
            row.delivered_at = utc_now()
        if release_claim:
            # Retries remain until the budget is spent; releasing the claim is
            # what lets another worker pick it up.
            row.claimed_at = None
            if row.attempts >= MAX_ALERT_ATTEMPTS:
                row.status = InternalAlertStatus.FAILED.value
        elif status is not None:
            row.status = status.value
        await self._session.commit()
        return True

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
        row.acknowledged_at = utc_now()
        await self._session.flush()
        return True
