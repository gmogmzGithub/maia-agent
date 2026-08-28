"""Product's own commercial upkeep: staleness, dormancy, content expiry.

Three rules that are about the passage of time rather than about anybody's
decision, so they run on the background loop and take no Actor from outside.

Dormancy deserves a note. ADR-0021 says silence after day 28 produces a Dormant
Opportunity **with a recorded reason**, not a Lost one — a distinction that only
means something if something actually performs the transition. The sweep is
restricted to Opportunities that never reached Qualified: past that point the
work belongs to a Responsible Advisor with a Next Action, and a background job
concluding on their behalf would be Product guessing at a human's judgement.

Nothing here sends a message. The Stage 1 eligibility gate remains the only path
to a Contact, and it is untouched: making an Opportunity Dormant is a record of
what the operation knows, not an outreach decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import Opportunity, OpportunityStage
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.commercial.needs import PropertyNeeds
from realestate.domain.commercial.opportunities import (
    DormantReason,
    OpportunityManagement,
    RecordDormant,
)
from realestate.domain.commercial.retention import ConversationRetention

logger = logging.getLogger(__name__)

# ADR-0021's conservative hypothesis ends on day 28. Silence past it is
# dormancy, and dormancy is explicitly not a loss.
DORMANCY_DAYS = 28

#: How often the pass is worth running. Declared beside the rules because it is
#: a property of them: the shortest horizon here is 28 days, so a quarter-hour
#: is indistinguishable from a second to every one of them — while running on
#: the Inbox loop's one-second cadence means ~86,400 passes a day, almost all of
#: them scanning to discover there is nothing to do.
#:
#: The interval is enforced by :class:`~realestate.worker.upkeep.CommercialUpkeepWorker`,
#: which is the only object that lives long enough to remember the last pass.
UPKEEP_INTERVAL_SECONDS = 900.0

DORMANCY_CONDITION = (
    "Retomar si el contacto responde o si aparece inventario nuevo que coincida "
    "con lo que buscaba."
)

# Only pre-qualification stages. See the module docstring.
SWEEPABLE_STAGES = (
    OpportunityStage.NEW.value,
    OpportunityStage.IN_CONVERSATION.value,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class MaintenanceReport:
    """What one upkeep pass changed."""

    stale_needs: int = 0
    dormant_opportunities: int = 0
    expired_conversations: int = 0

    @property
    def any(self) -> bool:
        return bool(
            self.stale_needs or self.dormant_opportunities or self.expired_conversations
        )


class CommercialMaintenance:
    """The commercial upkeep module. One entry point for the background loop."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, *, now: datetime | None = None) -> MaintenanceReport:
        """Run every time-driven commercial rule once. Commits per rule.

        Deliberately not one transaction. These rules are independent, and a
        failure in dormancy must not undo the staleness marking that already
        succeeded — nor stop content expiry, which is a retention obligation.
        """
        moment = now or _now()
        stale = await PropertyNeeds(self._session).refresh_stale(now=moment)
        dormant = await self.sweep_dormancy(now=moment)
        expired = await ConversationRetention(self._session).expire(now=moment)
        report = MaintenanceReport(
            stale_needs=stale,
            dormant_opportunities=dormant,
            expired_conversations=expired.conversations,
        )
        if report.any:
            logger.info(
                "Commercial upkeep: %d stale need(s), %d dormant, %d expired",
                report.stale_needs,
                report.dormant_opportunities,
                report.expired_conversations,
            )
        return report

    async def sweep_dormancy(
        self,
        *,
        now: datetime | None = None,
        days: int = DORMANCY_DAYS,
        limit: int = 100,
    ) -> int:
        """Pause unanswered pre-qualification Opportunities. Commits."""
        moment = now or _now()
        cutoff = moment - timedelta(days=days)
        candidates = list(
            await self._session.scalars(
                select(Opportunity)
                .where(Opportunity.stage.in_(SWEEPABLE_STAGES))
                .where(Opportunity.last_activity_at <= cutoff)
                .order_by(Opportunity.last_activity_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        if not candidates:
            return 0

        management = OpportunityManagement(self._session)
        recorded = 0
        stamp = moment.date().isoformat()
        for opportunity in candidates:
            actor = Actor.product(opportunity.organization_id, "DormancySweep")
            try:
                result = await management.record(
                    actor,
                    RecordDormant(
                        opportunity_id=opportunity.id,
                        reason=DormantReason.NO_RESPONSE,
                        revisit_condition=DORMANCY_CONDITION,
                        # Dated, so an Opportunity that is reactivated and goes
                        # silent again can be paused a second time instead of
                        # replaying the first decision forever.
                        command_key=f"dormancy:{opportunity.id}:{stamp}",
                        at=moment,
                    ),
                )
            except CommercialError as exc:
                # A concurrent human decision moved it. Their judgement wins;
                # the sweep records why it stood down rather than retrying.
                logger.info(
                    "Skipped dormancy for Opportunity %s: %s",
                    opportunity.id,
                    exc.message,
                )
                continue
            if not result.replayed:
                recorded += 1
        await self._session.commit()
        return recorded
