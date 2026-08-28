"""The human-operation tick: escalations, internal alerts, visit reminders.

Three responsibilities that share a cadence and nothing else, kept in one worker
because each is a few lines of "ask the module what is due, then do it" and
splitting them would produce three files of scaffolding.

Selection lives in the domain modules, sending lives here. That is the same
division :mod:`realestate.worker.broker` already uses, and it is what makes
"who gets alerted after fifteen minutes" testable without a Telegram token.

The worker holds no policy. It does not know that the escalation threshold is
fifteen minutes, that a reminder cadence is unvalidated, or who an alert is
addressed to. It knows how to send a Telegram message and how to record that it
did.
"""

from __future__ import annotations

import logging

from realestate.channels.telegram.client import TelegramClient
from realestate.db.engine import Database
from realestate.domain.availability import WeeklySchedule
from realestate.domain.commercial.handoff import HumanHandoff
from realestate.domain.internal_alerts import InternalAlerts
from realestate.domain.scheduling.reminders import AppointmentReminders

logger = logging.getLogger(__name__)


class OperationsWorker:
    def __init__(
        self,
        database: Database,
        telegram: TelegramClient,
        *,
        schedule: WeeklySchedule,
        day_of_reminder_hour: int,
        administrator_chat_ids: frozenset[str],
    ) -> None:
        self._database = database
        self._telegram = telegram
        self._schedule = schedule
        self._day_of_reminder_hour = day_of_reminder_hour
        # The Telegram ids configured for the Administrative Channel. Used only
        # as the fallback for an alert addressed to "every Administrator" whose
        # members have no per-person chat configured, so an escalation is never
        # silently undeliverable on a local setup that already works.
        self._administrator_chat_ids = administrator_chat_ids

    async def tick(self) -> None:
        await self._escalate()
        await self._deliver_alerts()
        await self._settle_reminders()

    async def _escalate(self) -> None:
        async with self._database.session_scope() as session:
            await HumanHandoff(session).escalate_due()

    async def _deliver_alerts(self) -> None:
        async with self._database.session_scope() as session:
            alerts = InternalAlerts(session)
            for claimed in await alerts.claim_due():
                chat_ids = claimed.chat_ids or (
                    tuple(self._administrator_chat_ids)
                    if claimed.alert.recipient_member_id is None
                    else ()
                )
                if not chat_ids:
                    await alerts.mark_undeliverable(
                        claimed.alert.id,
                        "El destinatario no tiene canal de alertas configurado.",
                    )
                    continue
                body = f"{claimed.alert.title}\n\n{claimed.alert.body}"
                failures: list[str] = []
                for chat_id in chat_ids:
                    if not await self._telegram.send_message(chat_id, body):
                        failures.append(chat_id)
                if failures:
                    await alerts.mark_failed(
                        claimed.alert.id,
                        "Telegram no aceptó el envío a: " + ", ".join(failures),
                    )
                    logger.error(
                        "Internal alert %s could not be delivered: %s",
                        claimed.alert.id,
                        failures,
                    )
                else:
                    await alerts.mark_sent(claimed.alert.id)

    async def _settle_reminders(self) -> None:
        async with self._database.session_scope() as session:
            outcomes = await AppointmentReminders(
                session, self._schedule, day_of_hour=self._day_of_reminder_hour
            ).settle_due()
        if outcomes:
            logger.info("Settled due visit reminders: %s", outcomes)
