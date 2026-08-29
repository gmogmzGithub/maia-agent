"""The Administrative Channel worker (P-040, ADR-0001).

Polls Telegram, persists each update durably, and runs authorised messages
through a *separate* Administrative Role session. Administrative work has its
own capacity and never consumes one of the three live-Lead slots (P-037).

Two boundaries matter here and are enforced before the Model sees anything:

* only allowlisted Telegram identities reach the Administrative Role;
* an unauthorised sender's message is still persisted — an attempt is exactly
  what an audit trail should record — but produces no session, no turn, and no
  reply.

Stage 9 adds a third, and it is the reason this worker resolves an Organization
before it polls: the process runs **one** bot token, so the administrative
channel belongs to exactly one Brokerage Organization. Which one is a lookup
against the ``TelegramBotId`` channel binding, not an assumption. Without a
binding the worker does nothing and says so — because the alternative, defaulting
to whichever Organization happens to exist, would let one brokerage's
administrator change another's inventory through Maia.

That the platform runs a single administrative bot is a Stage 9 operating limit
rather than a design: a second Organization needs its own token, and polling
several is a change to this worker, not to the boundary above.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.telegram.client import TelegramClient, TelegramUpdate
from realestate.db.engine import Database
from realestate.db.models import (
    AdminMessage,
    AgentRole,
    AgentSession,
    ChannelBindingKind,
    ChannelCursor,
)
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.routing import OrganizationRouting
from realestate.hermes.client import HermesClient
from realestate.hermes.sessions import RoleSession, bind_channel_session, run_turn

logger = logging.getLogger(__name__)

CHANNEL = "telegram"


class TelegramAdminWorker:
    def __init__(
        self,
        database: Database,
        hermes: HermesClient,
        telegram: TelegramClient,
        *,
        admin_profile: str,
        allowed_user_ids: frozenset[str],
    ) -> None:
        self._database = database
        self._hermes = hermes
        self._telegram = telegram
        self._admin_profile = admin_profile
        self._allowed = allowed_user_ids
        # Resolved on the first tick and remembered: the binding does not change
        # while the process runs, and a lookup per poll would be a query a
        # second for a value that is constant.
        self._organization_id: uuid.UUID | None = None
        self._unbound_reported = False

    async def _organization(self) -> uuid.UUID | None:
        """The Organization this bot's administrative channel belongs to.

        ``None`` means no Organization claims it, and then nothing is polled.
        Reported once rather than every second, because a wedged channel should
        be obvious in the log without drowning it.
        """
        if self._organization_id is not None:
            return self._organization_id
        async with self._database.session_scope() as session:
            try:
                routed = await OrganizationRouting(session).resolve(
                    ChannelBindingKind.TELEGRAM_BOT, self._telegram.bot_id
                )
            except CommercialError as exc:
                if not self._unbound_reported:
                    logger.warning(
                        "The Telegram administrative channel for bot %s is not "
                        "bound to an Organization, so no administrative message "
                        "will be processed: %s",
                        self._telegram.bot_id or "<unconfigured>",
                        exc.message,
                    )
                    self._unbound_reported = True
                return None
        self._organization_id = routed.organization_id
        logger.info(
            "The Telegram administrative channel serves Organization %s (%s)",
            routed.slug,
            routed.organization_id,
        )
        return self._organization_id

    async def tick(self) -> None:
        if not self._telegram.configured or not self._allowed:
            return
        organization_id = await self._organization()
        if organization_id is None:
            return

        updates = await self._telegram.get_updates(await self._cursor(organization_id))
        for update in updates:
            try:
                await self._handle(update, organization_id)
            except Exception:
                logger.exception("Administrative message %s failed", update.update_id)
            finally:
                # Advance past the update regardless. A failed administrative
                # turn is recorded and reported; replaying it forever would
                # wedge the channel and re-execute nothing useful.
                await self._advance(update.update_id, organization_id)

    # -- Cursor -----------------------------------------------------------

    async def _cursor(self, organization_id: uuid.UUID) -> int:
        async with self._database.session_scope() as session:
            row = await session.get(ChannelCursor, (organization_id, CHANNEL))
            return row.cursor if row else 0

    async def _advance(self, update_id: int, organization_id: uuid.UUID) -> None:
        async with self._database.session_scope() as session:
            row = await session.get(ChannelCursor, (organization_id, CHANNEL))
            if row is None:
                session.add(
                    ChannelCursor(
                        organization_id=organization_id,
                        channel=CHANNEL,
                        cursor=update_id + 1,
                    )
                )
            elif update_id + 1 > row.cursor:
                row.cursor = update_id + 1
            await session.commit()

    # -- One message ------------------------------------------------------

    async def _handle(
        self, update: TelegramUpdate, organization_id: uuid.UUID
    ) -> None:
        authorized = update.from_user_id in self._allowed

        async with self._database.session_scope() as session:
            existing = (
                await session.execute(
                    select(AdminMessage)
                    # Telegram numbers updates per bot, so the identifier is
                    # only unique inside one Organization.
                    .where(AdminMessage.organization_id == organization_id)
                    .where(AdminMessage.update_id == update.update_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Telegram re-delivered an update we already acted on.
                return

            record = AdminMessage(
                organization_id=organization_id,
                update_id=update.update_id,
                chat_id=update.chat_id,
                from_user_id=update.from_user_id,
                from_username=update.from_username,
                text=update.text,
                authorized=authorized,
                received_at=update.sent_at,
                raw_update=update.raw,
            )
            session.add(record)
            await session.commit()
            message_id = str(record.id)

        if not authorized:
            logger.warning(
                "Ignored an administrative message from unauthorised Telegram user %s",
                update.from_user_id,
            )
            return
        if not (update.text or "").strip():
            return

        reply = await self._run_admin_turn(update, message_id, organization_id)
        if reply and not await self._telegram.send_message(update.chat_id, reply):
            # Otherwise a rejected send looks identical to a delivered one:
            # the message is marked processed either way.
            logger.error(
                "Telegram rejected the reply to chat %s (message %s)",
                update.chat_id,
                message_id,
            )

        async with self._database.session_scope() as session:
            stored = await session.get(AdminMessage, message_id)
            if stored is not None:
                stored.processed_at = datetime.now(tz=UTC)
                await session.commit()

    async def _run_admin_turn(
        self, update: TelegramUpdate, message_id: str, organization_id: uuid.UUID
    ) -> str:
        """One turn on this administrator's persistent Administrative session."""
        async with self._database.session_scope() as session:
            binding = (
                await session.execute(
                    select(AgentSession)
                    .where(AgentSession.organization_id == organization_id)
                    .where(AgentSession.channel_key == self._channel_key(update))
                )
            ).scalar_one_or_none()
            role_session = RoleSession(
                gateway_session_id="",
                hermes_session_id=binding.hermes_session_id if binding else "",
                role=AgentRole.ADMINISTRATIVE,
            )

        async def bind(hermes_session_id: str) -> None:
            # Must land before the Model can reach a tool: the Backend resolves
            # Administrative authority from this row.
            async with self._database.session_scope() as session:
                await self._bind(session, update, hermes_session_id, organization_id)

        turn = await run_turn(
            self._hermes,
            role_session,
            update.text or "",
            profile=self._admin_profile,
            on_attached=bind,
        )
        if turn.tools_used:
            logger.info(
                "Administrative turn for %s used: %s",
                update.from_user_id,
                ", ".join(turn.tools_used),
            )
        return turn.text

    def _channel_key(self, update: TelegramUpdate) -> str:
        return f"{CHANNEL}:{update.chat_id}"

    async def _bind(
        self,
        session: AsyncSession,
        update: TelegramUpdate,
        hermes_session_id: str,
        organization_id: uuid.UUID,
    ) -> None:
        await bind_channel_session(
            session,
            organization_id=organization_id,
            role=AgentRole.ADMINISTRATIVE,
            channel_key=self._channel_key(update),
            hermes_session_id=hermes_session_id,
        )
