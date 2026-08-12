"""The Administrative Channel worker (P-040, ADR-0001).

Polls Telegram, persists each update durably, and runs authorised messages
through a *separate* Administrative Role session. Administrative work has its
own capacity and never consumes one of the three live-Lead slots (P-037).

Two boundaries matter here and are enforced before the Model sees anything:

* only allowlisted Telegram identities reach the Administrative Role;
* an unauthorised sender's message is still persisted — an attempt is exactly
  what an audit trail should record — but produces no session, no turn, and no
  reply.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from realestate.channels.telegram.client import TelegramClient, TelegramUpdate
from realestate.db.engine import Database
from realestate.db.models import AdminMessage, AgentRole, AgentSession, ChannelCursor
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

    async def tick(self) -> None:
        if not self._telegram.configured or not self._allowed:
            return

        updates = await self._telegram.get_updates(await self._cursor())
        for update in updates:
            try:
                await self._handle(update)
            except Exception:
                logger.exception("Administrative message %s failed", update.update_id)
            finally:
                # Advance past the update regardless. A failed administrative
                # turn is recorded and reported; replaying it forever would
                # wedge the channel and re-execute nothing useful.
                await self._advance(update.update_id)

    # -- Cursor -----------------------------------------------------------

    async def _cursor(self) -> int:
        async with self._database.session_scope() as session:
            row = await session.get(ChannelCursor, CHANNEL)
            return row.cursor if row else 0

    async def _advance(self, update_id: int) -> None:
        async with self._database.session_scope() as session:
            row = await session.get(ChannelCursor, CHANNEL)
            if row is None:
                session.add(ChannelCursor(channel=CHANNEL, cursor=update_id + 1))
            elif update_id + 1 > row.cursor:
                row.cursor = update_id + 1
            await session.commit()

    # -- One message ------------------------------------------------------

    async def _handle(self, update: TelegramUpdate) -> None:
        authorized = update.from_user_id in self._allowed

        async with self._database.session_scope() as session:
            existing = (
                await session.execute(
                    select(AdminMessage).where(AdminMessage.update_id == update.update_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Telegram re-delivered an update we already acted on.
                return

            record = AdminMessage(
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

        reply = await self._run_admin_turn(update, message_id)
        if reply and not await self._telegram.send_message(update.chat_id, reply):
            # Otherwise a rejected send looks identical to a delivered one:
            # the message is marked processed either way.
            logger.error(
                "Telegram rejected the reply to chat %s (message %s)",
                update.chat_id,
                message_id,
            )

        async with self._database.session_scope() as session:
            record = await session.get(AdminMessage, message_id)
            if record is not None:
                record.processed_at = datetime.now(tz=UTC)
                await session.commit()

    async def _run_admin_turn(self, update: TelegramUpdate, message_id: str) -> str:
        """One turn on this administrator's persistent Administrative session."""
        async with self._database.session_scope() as session:
            binding = (
                await session.execute(
                    select(AgentSession).where(
                        AgentSession.channel_key == self._channel_key(update)
                    )
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
                await self._bind(session, update, hermes_session_id)

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

    async def _bind(self, session, update: TelegramUpdate, hermes_session_id: str) -> None:  # noqa: ANN001
        await bind_channel_session(
            session,
            role=AgentRole.ADMINISTRATIVE,
            channel_key=self._channel_key(update),
            hermes_session_id=hermes_session_id,
        )
