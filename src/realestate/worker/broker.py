"""The Broker-notification worker (amendment 2 in checkpoint-3-inputs.md).

A thin sender. Every rule about which notice is owed lives in
:mod:`realestate.domain.notifications`; this class does three things per tick:
retire reminders whose visit already started, ask for the due notices, and put
them on Telegram — stamping only what Telegram accepted.

Two failure behaviours are deliberate:

* a notice is stamped when **at least one** recipient accepted it. Stamping only
  on unanimous success would mean a single unreachable administrator — a Telegram
  bot cannot message someone who never started a chat with it — turns every tick
  into another delivery to everyone else, forever.
* when no recipient accepts, the whole tick backs off. The loop ticks once a
  second; retrying a broken send at that rate would be a Telegram request flood
  with nothing delivered at the end of it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from realestate.channels.telegram.client import TelegramClient
from realestate.db.engine import Database
from realestate.domain.availability import WeeklySchedule
from realestate.domain.notifications import BrokerNotice, BrokerNotificationService

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = 60


class BrokerNotifier:
    def __init__(
        self,
        database: Database,
        telegram: TelegramClient,
        *,
        chat_ids: frozenset[str],
        schedule: WeeklySchedule,
        digest_hour: int,
        reminder_minutes: int,
    ) -> None:
        self._database = database
        self._telegram = telegram
        # Stage 0 gives the Broker and the Developer identical administrative
        # authority (ADR-0001), and there is no separate Broker identity to
        # address, so both allowlisted Telegram identities receive these.
        self._chat_ids = chat_ids
        self._schedule = schedule
        self._digest_hour = digest_hour
        self._reminder_minutes = reminder_minutes
        self._retry_after: datetime | None = None

    async def tick(self) -> None:
        if not self._telegram.configured or not self._chat_ids:
            return
        now = datetime.now(tz=UTC)
        if self._retry_after is not None and now < self._retry_after:
            return

        async with self._database.session_scope() as session:
            service = BrokerNotificationService(
                session,
                self._schedule,
                digest_hour=self._digest_hour,
                reminder_minutes=self._reminder_minutes,
            )

            lapsed = await service.lapse_stale_reminders(now)
            if lapsed:
                logger.warning(
                    "Dropped %d Broker reminder(s) whose visit had already started",
                    lapsed,
                )

            for notice in await service.due(now):
                if await self._send(notice):
                    await service.mark_sent(notice, now)
                else:
                    self._retry_after = now + timedelta(seconds=RETRY_AFTER_SECONDS)
                    logger.error(
                        "No administrator accepted the %s notice; retrying in %ds",
                        notice.kind,
                        RETRY_AFTER_SECONDS,
                    )
                    return

    async def _send(self, notice: BrokerNotice) -> bool:
        accepted = 0
        for chat_id in sorted(self._chat_ids):
            if await self._telegram.send_message(chat_id, notice.body):
                accepted += 1
            else:
                logger.error(
                    "Telegram rejected the %s notice to chat %s", notice.kind, chat_id
                )
        if accepted:
            logger.info(
                "Sent the %s notice to %d administrator(s) for %d appointment(s)",
                notice.kind,
                accepted,
                len(notice.appointment_ids),
            )
        return accepted > 0
