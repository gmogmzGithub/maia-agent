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
import uuid

from realestate.channels.telegram.client import TelegramClient
from realestate.db.engine import Database
from realestate.domain.availability import WeeklySchedule
from realestate.domain.commercial.handoff import HumanHandoff
from realestate.domain.internal_alerts import InternalAlerts
from realestate.domain.scheduling.reminders import AppointmentReminders
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.providers import (
    OrganizationTelegramClients,
    organization_administrator_chat_ids,
)
from realestate.domain.platform.registry import operating_organization_ids
from realestate.domain.platform.runtime import OrganizationAppointmentPolicies

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
        organization_id: uuid.UUID | None = None,
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
        self._organization_id = organization_id

    async def tick(self) -> None:
        await self._escalate()
        await self._deliver_alerts()
        await self._settle_reminders()

    async def _escalate(self) -> None:
        async with self._database.session_scope() as session:
            await HumanHandoff(session).escalate_due(
                organization_id=self._organization_id
            )

    async def _deliver_alerts(self) -> None:
        async with self._database.session_scope() as session:
            alerts = InternalAlerts(session)
            for claimed in await alerts.claim_due(
                organization_id=self._organization_id
            ):
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
                session,
                self._schedule,
                day_of_hour=self._day_of_reminder_hour,
                organization_id=self._organization_id,
            ).settle_due()
        if outcomes:
            logger.info("Settled due visit reminders: %s", outcomes)


class OrganizationOperationsWorkers:
    """Run alerts and reminders with each Organization's bot and schedule."""

    def __init__(
        self,
        database: Database,
        clients: OrganizationTelegramClients,
        policies: OrganizationAppointmentPolicies,
    ) -> None:
        self._database = database
        self._clients = clients
        self._policies = policies
        self._workers: dict[
            uuid.UUID,
            tuple[TelegramClient, frozenset[str], AppointmentPolicy, OperationsWorker],
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
                worker = OperationsWorker(
                    self._database,
                    client,
                    schedule=policy.schedule,
                    day_of_reminder_hour=policy.day_of_reminder_hour,
                    administrator_chat_ids=chat_ids,
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
