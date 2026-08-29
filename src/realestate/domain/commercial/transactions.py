"""Transactions are deals, not pipeline stages (ADR-0032)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import CommercialTransaction, OpportunityOrigin
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, InvalidTransition
from realestate.domain.commercial.records import visible_opportunity


@dataclass(frozen=True)
class RecordTransaction:
    opportunity_id: uuid.UUID
    evidence: str
    evidence_detail: str
    completed_at: datetime
    command_key: str


class Transactions:
    """Create and read the one deal produced by a Won Opportunity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self, actor: Actor, command: RecordTransaction
    ) -> CommercialTransaction:
        actor.require_administrator()
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(command.command_key)))
        )
        existing = await self._session.scalar(
            select(CommercialTransaction).where(
                CommercialTransaction.command_key == command.command_key
            )
        )
        if existing is not None:
            actor.require_same_organization(existing.organization_id)
            if (
                existing.opportunity_id != command.opportunity_id
                or existing.evidence != command.evidence
                or existing.evidence_detail != command.evidence_detail
                or existing.completed_at != command.completed_at
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
            return existing

        opportunity = await visible_opportunity(
            self._session, actor, command.opportunity_id, lock=True
        )
        if opportunity.stage != "Won":
            raise InvalidTransition(
                "Sólo una oportunidad ganada puede producir una transacción."
            )
        if (
            opportunity.won_evidence != command.evidence
            or opportunity.won_evidence_detail != command.evidence_detail
            or opportunity.won_recorded_by != actor.member_id
        ):
            raise InvalidTransition(
                "La evidencia de la transacción no coincide con la oportunidad ganada."
            )
        by_opportunity = await self._session.scalar(
            select(CommercialTransaction).where(
                CommercialTransaction.opportunity_id == opportunity.id
            )
        )
        if by_opportunity is not None:
            raise InvalidTransition(
                "Esta oportunidad ya produjo una transacción registrada."
            )
        origin = await self._session.scalar(
            select(OpportunityOrigin).where(
                OpportunityOrigin.opportunity_id == opportunity.id
            )
        )
        row = CommercialTransaction(
            organization_id=opportunity.organization_id,
            opportunity_id=opportunity.id,
            contact_id=opportunity.contact_id,
            property_uuid=origin.property_uuid if origin is not None else None,
            evidence=command.evidence,
            evidence_detail=command.evidence_detail,
            accepted_by=actor.member_id,
            command_key=command.command_key,
            completed_at=command.completed_at,
        )
        self._session.add(row)
        await self._session.flush()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="RecordCommercialTransaction",
            subject_type="CommercialTransaction",
            subject_id=str(row.id),
            details={
                "opportunity_id": str(opportunity.id),
                "evidence": command.evidence,
                "property_known": row.property_uuid is not None,
            },
            commit=False,
        )
        return row

    async def for_opportunity(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> CommercialTransaction | None:
        await visible_opportunity(self._session, actor, opportunity_id)
        row = await self._session.scalar(
            select(CommercialTransaction).where(
                CommercialTransaction.opportunity_id == opportunity_id
            )
        )
        return row
