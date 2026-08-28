"""Property Needs: what the Contact wants, and how sure Product is about it.

ADR-0031 is the whole design. Hermes may interpret natural language and propose
normalised criteria, but a material value the Contact did not state stays
**Pending** until they confirm it. Pending values are visible, usable in
conversation, and useless for qualification — which is exactly the asymmetry
that lets a probabilistic reader improve the experience without quietly becoming
the basis for who gets called.

Criteria are append-only per name. Confirming or changing one supersedes the
previous row rather than overwriting it, so "Maia understood 3 recámaras and the
Contact later said 2" survives as history instead of becoming a value with no
provenance.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    PROPERTY_NEED_STALE_DAYS,
    Contact,
    CriterionSource,
    CriterionState,
    PropertyNeed,
    PropertyNeedCriterion,
    PropertyNeedStatus,
    TransactionIntent,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, NotFound

logger = logging.getLogger(__name__)

# The minimum a Qualified Opportunity needs, from PROJECT_MEMORY's definition:
# transaction intent, acceptable area, economic range, approximate horizon and
# essential requirements. The sixth element of that definition — a legitimate
# contact path — is not a criterion here, because it is not something a Contact
# can state: it is the Verified channel identity Product already holds, checked
# where qualification happens.
INTENT = "transaction_intent"
SERVICE_AREA = "service_area"
ECONOMIC_RANGE = "economic_range"
HORIZON = "horizon"
ESSENTIAL_REQUIREMENTS = "essential_requirements"

REQUIRED_CRITERIA: tuple[str, ...] = (
    INTENT,
    SERVICE_AREA,
    ECONOMIC_RANGE,
    HORIZON,
    ESSENTIAL_REQUIREMENTS,
)

# Mexican Spanish labels for every surface that shows a criterion. Kept beside
# the names so a criterion cannot be added to the required set without the
# operator's screen gaining a word for it.
CRITERION_LABELS: dict[str, str] = {
    INTENT: "Tipo de operación",
    SERVICE_AREA: "Zona aceptable",
    ECONOMIC_RANGE: "Rango económico",
    HORIZON: "Horizonte aproximado",
    ESSENTIAL_REQUIREMENTS: "Requisitos esenciales",
}

NEED_STATUS_LABELS: dict[str, str] = {
    PropertyNeedStatus.ACTIVE.value: "Vigente",
    PropertyNeedStatus.STALE.value: "Sin confirmar (más de 90 días)",
}

SOURCE_LABELS: dict[str, str] = {
    CriterionSource.CONTACT_STATED.value: "Lo dijo el contacto",
    CriterionSource.MODEL_INFERRED.value: "Interpretado por Maia",
    CriterionSource.ADVISOR_RECORDED.value: "Registrado por un asesor",
}

INTENT_LABELS: dict[str, str] = {
    TransactionIntent.BUY.value: "Compra",
    TransactionIntent.RENT.value: "Renta",
    TransactionIntent.SELL.value: "Venta de su propiedad",
    TransactionIntent.LEASE_OUT.value: "Renta de su propiedad",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def criterion_label(name: str) -> str:
    """A Spanish label for any criterion, including ones Maia invents."""
    return CRITERION_LABELS.get(name, name.replace("_", " ").capitalize())


@dataclass(frozen=True)
class CriterionStatement:
    """One value for one named criterion, with where it came from."""

    name: str
    value: str
    state: CriterionState
    source: CriterionSource
    evidence: str | None = None

    @classmethod
    def inferred(
        cls, name: str, value: str, *, evidence: str | None = None
    ) -> CriterionStatement:
        """What Hermes understood. Pending by construction — ADR-0031."""
        return cls(
            name=name,
            value=value,
            state=CriterionState.PENDING,
            source=CriterionSource.MODEL_INFERRED,
            evidence=evidence,
        )

    @classmethod
    def stated(
        cls, name: str, value: str, *, evidence: str | None = None
    ) -> CriterionStatement:
        """What the Contact said explicitly. Confirmed commercial truth."""
        return cls(
            name=name,
            value=value,
            state=CriterionState.CONFIRMED,
            source=CriterionSource.CONTACT_STATED,
            evidence=evidence,
        )

    @classmethod
    def recorded(
        cls, name: str, value: str, *, evidence: str | None = None
    ) -> CriterionStatement:
        """What an Advisor recorded on the Contact's behalf. Confirmed."""
        return cls(
            name=name,
            value=value,
            state=CriterionState.CONFIRMED,
            source=CriterionSource.ADVISOR_RECORDED,
            evidence=evidence,
        )


@dataclass(frozen=True)
class NeedSnapshot:
    """Everything a caller needs to judge one Property Need at one moment."""

    need_id: uuid.UUID
    status: PropertyNeedStatus
    confirmed: dict[str, str]
    pending: dict[str, str]
    last_confirmed_at: datetime | None

    @property
    def missing_required(self) -> tuple[str, ...]:
        """Required criteria with no confirmed value, in declaration order."""
        return tuple(
            name for name in REQUIRED_CRITERIA if name not in self.confirmed
        )

    @property
    def pending_required(self) -> tuple[str, ...]:
        """Required criteria whose only value is an unconfirmed interpretation.

        Reported separately from ``missing_required`` because the operator's
        next action differs: one needs a question asked, the other needs a
        confirmation obtained.
        """
        return tuple(name for name in self.missing_required if name in self.pending)

    @property
    def is_stale(self) -> bool:
        return self.status is PropertyNeedStatus.STALE

    @property
    def meets_minimum(self) -> bool:
        """Whether the accepted minimum criteria are confirmed.

        A Stale need does not meet it regardless of what it once contained: it
        may only identify a possible reactivation, never current truth
        (ADR-0026).
        """
        return not self.missing_required and not self.is_stale


class PropertyNeeds:
    """The Property Need module.

    Hides: supersession, the confirmed/pending split, the 90-day staleness
    rule, reconfirmation, Organization scoping, and the audit trail. Callers ask
    for a snapshot and get an answer, not a criteria table to interpret.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open(
        self,
        actor: Actor,
        *,
        contact_id: uuid.UUID,
    ) -> PropertyNeed:
        """Start a Property Need for a Contact. Never commits.

        No intent is assumed. An empty need is the honest starting state for an
        inquiry whose first message has not been read yet, and it is what gives
        the CRM something to attach Pending interpretations to.
        """
        contact = await self._session.get(Contact, contact_id)
        if contact is None:
            raise NotFound("No encontramos ese contacto.")
        actor.require_same_organization(contact.organization_id)
        need = PropertyNeed(
            organization_id=actor.organization_id,
            contact_id=contact_id,
            status=PropertyNeedStatus.ACTIVE.value,
        )
        self._session.add(need)
        await self._session.flush()
        return need

    async def need(self, actor: Actor, need_id: uuid.UUID) -> PropertyNeed:
        need = await self._session.get(PropertyNeed, need_id)
        if need is None:
            raise NotFound("No encontramos esa necesidad.")
        actor.require_same_organization(need.organization_id)
        return need

    async def record(
        self,
        actor: Actor,
        need_id: uuid.UUID,
        statements: Sequence[CriterionStatement],
        *,
        now: datetime | None = None,
    ) -> NeedSnapshot:
        """Write criteria, superseding the current value of each name.

        Never commits. Recording a Confirmed value refreshes the need's
        confirmation clock and revives it from Stale; recording a Pending one
        deliberately does not, because an interpretation is not a confirmation.
        """
        need = await self.need(actor, need_id)
        moment = now or _now()
        current = await self._current(need.id)
        confirmed_any = False
        written: list[str] = []

        for statement in statements:
            if statement.state is CriterionState.CONFIRMED:
                # Set even when no row is written. Confirming is an *act*: the
                # Contact saying "yes, still 3.5 to 4.5 millones" refreshes the
                # staleness clock and revives a Stale need whether or not the
                # value moved. Skipping that would make a reconfirmation of an
                # unchanged need a no-op, which is exactly the case ADR-0026
                # asks the operation to perform.
                confirmed_any = True
            if self._already_current(current.get(statement.name), statement):
                # No new row. Superseding a row with an identical successor
                # would turn a retried request into fabricated history, and the
                # criteria table is the provenance record ADR-0031 relies on.
                continue
            written.append(statement.name)
            await self._supersede(need.id, statement.name, moment)
            self._session.add(
                PropertyNeedCriterion(
                    organization_id=need.organization_id,
                    property_need_id=need.id,
                    name=statement.name,
                    value=statement.value,
                    state=statement.state.value,
                    source=statement.source.value,
                    evidence=statement.evidence,
                    recorded_at=moment,
                    confirmed_at=(
                        moment if statement.state is CriterionState.CONFIRMED else None
                    ),
                )
            )
            if statement.state is CriterionState.CONFIRMED:
                if statement.name == INTENT:
                    # Denormalised for the CRM's list queries. The criterion row
                    # remains the evidence; this column is only ever written
                    # here, from a Confirmed statement.
                    need.transaction_intent = (
                        statement.value
                        if statement.value
                        in {intent.value for intent in TransactionIntent}
                        else None
                    )

        if confirmed_any:
            need.last_confirmed_at = moment
            if need.status == PropertyNeedStatus.STALE.value:
                need.status = PropertyNeedStatus.ACTIVE.value
                need.became_stale_at = None
                await record_audit(
                    self._session,
                    actor_type=actor.actor_type,
                    actor_id=actor.label,
                    action="ReconfirmPropertyNeed",
                    subject_type="PropertyNeed",
                    subject_id=str(need.id),
                    details={"criteria": written},
                    commit=False,
                )
        if written or confirmed_any:
            # Confirming a criterion is the evidence that gates Qualified, so it
            # belongs in the same trail as the stage change it enables. Criterion
            # values are deliberately not copied here: the rows hold them, and
            # the audit trail outlives the retention rules for personal data.
            await record_audit(
                self._session,
                actor_type=actor.actor_type,
                actor_id=actor.label,
                action="RecordPropertyNeedCriteria",
                subject_type="PropertyNeed",
                subject_id=str(need.id),
                details={
                    "criteria": written,
                    "confirmed": [
                        s.name
                        for s in statements
                        if s.state is CriterionState.CONFIRMED and s.name in written
                    ],
                },
                commit=False,
            )
        need.updated_at = moment
        await self._session.flush()
        return await self.snapshot(need_id)

    async def confirm(
        self,
        actor: Actor,
        need_id: uuid.UUID,
        names: Sequence[str],
        *,
        source: CriterionSource = CriterionSource.CONTACT_STATED,
        now: datetime | None = None,
    ) -> NeedSnapshot:
        """Promote Pending interpretations to Confirmed truth. Never commits.

        The value is not re-supplied: confirming means "yes, that one", and
        letting the caller pass a different value at the same time would make
        the confirmation unauditable.
        """
        need = await self.need(actor, need_id)
        current = await self._current(need.id)
        statements: list[CriterionStatement] = []
        for name in names:
            row = current.get(name)
            if row is None or row.state != CriterionState.PENDING.value:
                # Nothing pending under that name. Silently skipping would let a
                # surface report a confirmation that never happened.
                raise NotFound(
                    f"No hay un criterio pendiente llamado «{criterion_label(name)}»."
                )
            statements.append(
                CriterionStatement(
                    name=name,
                    value=row.value,
                    state=CriterionState.CONFIRMED,
                    source=source,
                    evidence=row.evidence,
                )
            )
        return await self.record(actor, need_id, statements, now=now)

    async def snapshot(self, need_id: uuid.UUID) -> NeedSnapshot:
        """The current confirmed and pending values for one need."""
        need = await self._session.get(PropertyNeed, need_id)
        if need is None:
            raise NotFound("No encontramos esa necesidad.")
        current = await self._current(need_id)
        confirmed = {
            name: row.value
            for name, row in current.items()
            if row.state == CriterionState.CONFIRMED.value
        }
        pending = {
            name: row.value
            for name, row in current.items()
            if row.state == CriterionState.PENDING.value
        }
        return NeedSnapshot(
            need_id=need_id,
            status=PropertyNeedStatus(need.status),
            confirmed=confirmed,
            pending=pending,
            last_confirmed_at=need.last_confirmed_at,
        )

    async def history(self, need_id: uuid.UUID) -> list[PropertyNeedCriterion]:
        """Every criterion row, newest first. The provenance ADR-0031 requires."""
        rows = await self._session.scalars(
            select(PropertyNeedCriterion)
            .where(PropertyNeedCriterion.property_need_id == need_id)
            .order_by(
                PropertyNeedCriterion.recorded_at.desc(),
                PropertyNeedCriterion.id.desc(),
            )
        )
        return list(rows)

    async def needs_for_contact(self, contact_id: uuid.UUID) -> list[PropertyNeed]:
        rows = await self._session.scalars(
            select(PropertyNeed)
            .where(PropertyNeed.contact_id == contact_id)
            .order_by(PropertyNeed.created_at.desc())
        )
        return list(rows)

    async def refresh_stale(self, *, now: datetime | None = None) -> int:
        """Mark needs unconfirmed for 90 days as Stale. Commits.

        Product-owned maintenance, not an Actor's decision, which is why it
        takes no Actor and marks across every Organization: staleness is the
        passage of time.

        ``created_at`` is the fallback clock. A need nobody ever confirmed is
        exactly the case the rule exists for, so treating it as permanently
        fresh would be the wrong direction to fail in.
        """
        moment = now or _now()
        cutoff = moment - timedelta(days=PROPERTY_NEED_STALE_DAYS)
        result = await self._session.execute(
            update(PropertyNeed)
            .where(PropertyNeed.status == PropertyNeedStatus.ACTIVE.value)
            .where(
                func.coalesce(
                    PropertyNeed.last_confirmed_at, PropertyNeed.created_at
                )
                <= cutoff
            )
            .values(
                status=PropertyNeedStatus.STALE.value,
                became_stale_at=moment,
                updated_at=moment,
            )
            .returning(PropertyNeed.id)
        )
        stale_ids = [row[0] for row in result]
        for need_id in stale_ids:
            await record_audit(
                self._session,
                actor_type="Product",
                actor_id="PropertyNeeds",
                action="MarkPropertyNeedStale",
                subject_type="PropertyNeed",
                subject_id=str(need_id),
                details={"days_without_confirmation": PROPERTY_NEED_STALE_DAYS},
                commit=False,
            )
        await self._session.commit()
        if stale_ids:
            logger.info("Marked %d Property Need(s) Stale", len(stale_ids))
        return len(stale_ids)

    # -- internals ---------------------------------------------------------

    async def _current(
        self, need_id: uuid.UUID
    ) -> dict[str, PropertyNeedCriterion]:
        rows = await self._session.scalars(
            select(PropertyNeedCriterion)
            .where(PropertyNeedCriterion.property_need_id == need_id)
            .where(PropertyNeedCriterion.superseded_at.is_(None))
        )
        return {row.name: row for row in rows}

    @staticmethod
    def _already_current(
        row: PropertyNeedCriterion | None, statement: CriterionStatement
    ) -> bool:
        """Whether this exact statement is already the current value.

        Compares everything the row records, provenance included: the same value
        confirmed by the Contact is a *different* fact from the same value Maia
        inferred, and replacing one with the other is a real change.
        """
        if row is None:
            return False
        return (
            row.value == statement.value
            and row.state == statement.state.value
            and row.source == statement.source.value
            and row.evidence == statement.evidence
        )

    async def _supersede(
        self, need_id: uuid.UUID, name: str, moment: datetime
    ) -> None:
        await self._session.execute(
            update(PropertyNeedCriterion)
            .where(PropertyNeedCriterion.property_need_id == need_id)
            .where(PropertyNeedCriterion.name == name)
            .where(PropertyNeedCriterion.superseded_at.is_(None))
            .values(superseded_at=moment)
        )
