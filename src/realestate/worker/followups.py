"""Background worker for deterministic Lead follow-ups."""

from __future__ import annotations

import logging

from realestate.db.engine import Database
from realestate.domain.followups import LeadFollowUpService

logger = logging.getLogger(__name__)


class LeadFollowUpWorker:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def tick(self) -> None:
        async with self._database.session_scope() as session:
            run = await LeadFollowUpService(session).enqueue_due()
        if run.enqueued:
            logger.info("Enqueued %d Lead follow-up WhatsApp message(s)", run.enqueued)
        if run.blocked:
            # Not an error. A blocked attempt is the policy working: the reason
            # is on each OutboundDecision row (ADR-0045).
            logger.info(
                "Recorded %d Lead follow-up attempt(s) the eligibility gate refused",
                run.blocked,
            )
