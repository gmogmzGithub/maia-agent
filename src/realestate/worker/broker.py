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
import uuid
from datetime import UTC, datetime, timedelta

from realestate.channels.telegram.client import TelegramClient
from realestate.db.engine import Database
from realestate.domain.availability import WeeklySchedule
from realestate.domain.notifications import BrokerNotice, BrokerNotificationService
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.providers import (
    OrganizationTelegramClients,
    organization_administrator_chat_ids,
)
from realestate.domain.platform.registry import operating_organization_ids
from realestate.domain.platform.runtime import OrganizationAppointmentPolicies
from realestate.domain.appointments import AppointmentPolicy

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
        organization_id: uuid.UUID | None = None,
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
        self._organization_id = organization_id
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
                organization_id=self._organization_id,
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


class OrganizationBrokerNotifiers:
    """Deliver Broker notices through each Organization's bot and policy."""

    def __init__(
        self,
        database: Database,
        clients: OrganizationTelegramClients,
        policies: OrganizationAppointmentPolicies,
        *,
        digest_hour: int,
        reminder_minutes: int,
    ) -> None:
        self._database = database
        self._clients = clients
        self._policies = policies
        self._digest_hour = digest_hour
        self._reminder_minutes = reminder_minutes
        self._workers: dict[
            uuid.UUID,
            tuple[TelegramClient, frozenset[str], AppointmentPolicy, BrokerNotifier],
        ] = {}

    async def tick(self) -> None:
        configured: list[
            tuple[uuid.UUID, TelegramClient, frozenset[str], AppointmentPolicy]
        ] = []
        async with self._database.session_scope() as session:
            for organization_id in await operating_organization_ids(session):
                try:
                    client = await self._clients.for_organization(
                        session, organization_id
                    )
                    policy = await self._policies.for_organization(
                        session, organization_id
                    )
                except CommercialError:
                    continue
                chat_ids = await organization_administrator_chat_ids(
                    session, organization_id
                )
                configured.append((organization_id, client, chat_ids, policy))

        active_ids: set[uuid.UUID] = set()
        for organization_id, client, chat_ids, policy in configured:
            active_ids.add(organization_id)
            cached = self._workers.get(organization_id)
            if (
                cached is None
                or cached[0] is not client
                or cached[1] != chat_ids
                or cached[2] != policy
            ):
                worker = BrokerNotifier(
                    self._database,
                    client,
                    chat_ids=chat_ids,
                    schedule=policy.schedule,
                    digest_hour=self._digest_hour,
                    reminder_minutes=self._reminder_minutes,
                    organization_id=organization_id,
                )
                self._workers[organization_id] = (
                    client,
                    chat_ids,
                    policy,
                    worker,
                )
            await self._workers[organization_id][3].tick()

        for organization_id in tuple(self._workers):
            if organization_id not in active_ids:
                self._workers.pop(organization_id, None)
