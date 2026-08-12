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
            enqueued = await LeadFollowUpService(session).enqueue_due()
        if enqueued:
            logger.info("Enqueued %d Lead follow-up WhatsApp message(s)", enqueued)
