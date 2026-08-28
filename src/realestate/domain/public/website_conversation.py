"""Anonymous Website Conversation with Product-owned privacy and continuity."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    WebsiteConversation as WebsiteConversationRow,
    WebsiteConversationStatus,
    WebsiteMessage,
    WebsiteMessageRole,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.public.catalog import PublicListingView
from realestate.domain.public.listing import PublicListing
from realestate.domain.public.saved import token_hash

CONTENT_LIFETIME = timedelta(days=90)
MAX_MESSAGE_CHARS = 2_000
MAX_CONTEXT_LISTINGS = 12
_PHONE = re.compile(r"(?<!\d)(?:\+?52\s*)?(?:\d[\s().-]*){10,13}(?!\d)")
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
_MODEL_PII_REQUEST = re.compile(
    r"\b(?:tel[eé]fono|celular|correo|e-?mail|whatsapp)\b", re.IGNORECASE
)
_PRIVACY_REPLY = (
    "Para proteger tus datos, no escribas aquí tu teléfono ni correo. "
    "Puedes seguir por el WhatsApp oficial cuando quieras identificarte o solicitar una cita."
)


@dataclass(frozen=True)
class ConversationMessageView:
    role: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class WebsiteTurn:
    conversation_id: uuid.UUID
    hermes_session_id: str | None
    message: str
    history: tuple[ConversationMessageView, ...]
    listings: tuple[PublicListingView, ...]


@dataclass(frozen=True)
class WebsiteReply:
    text: str
    hermes_session_id: str


class WebsiteResponder(Protocol):
    async def respond(self, turn: WebsiteTurn) -> WebsiteReply: ...


@dataclass(frozen=True)
class WebsiteCommand:
    message: str
    command_key: str
    conversation_token: str | None = None
    listing_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class WebsiteConversationResult:
    conversation_id: uuid.UUID
    conversation_token: str | None
    reply: str
    messages: tuple[ConversationMessageView, ...]
    requires_verified_channel: bool
    replayed: bool


class WebsiteConversation:
    """Hide privacy checks, durable context, Hermes continuity and replay."""

    def __init__(
        self, session: AsyncSession, actor: Actor, responder: WebsiteResponder
    ) -> None:
        self._session = session
        self._actor = actor
        self._responder = responder
        self._public = PublicListing(session, actor)

    async def handle(
        self, command: WebsiteCommand, *, at: datetime
    ) -> WebsiteConversationResult:
        text = command.message.strip()
        if not text:
            raise ValueError("Escribe un mensaje para Maia.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError("El mensaje es demasiado largo.")
        row = await self._resolve(command.conversation_token, lock=True)
        issued: str | None = None
        if row is None:
            issued = f"wc-{secrets.token_urlsafe(32)}"
            row = WebsiteConversationRow(
                organization_id=self._actor.organization_id,
                access_token_hash=token_hash(issued),
                listing_context=[],
                status=WebsiteConversationStatus.OPEN.value,
                created_at=at,
                last_activity_at=at,
            )
            self._session.add(row)
            await self._session.flush()
        elif row.status == WebsiteConversationStatus.CLOSED.value:
            raise ValueError("Esta conversación terminó. Inicia una nueva.")

        replay = await self._replay(row.id, command.command_key)
        if replay is not None:
            return WebsiteConversationResult(
                row.id,
                issued,
                replay.body,
                await self._history(row.id, at=at),
                False,
                True,
            )

        listings = await self._context(row, command.listing_ids, at=at)
        if _contains_pii(text):
            return WebsiteConversationResult(
                row.id,
                issued,
                _PRIVACY_REPLY,
                await self._history(row.id, at=at),
                True,
                False,
            )

        history = await self._history(row.id, at=at)
        reply = await self._responder.respond(
            WebsiteTurn(
                conversation_id=row.id,
                hermes_session_id=row.hermes_session_id,
                message=text,
                history=history,
                listings=listings,
            )
        )
        safe_reply = reply.text.strip()
        requires_verified = False
        if not safe_reply or _MODEL_PII_REQUEST.search(safe_reply):
            safe_reply = _PRIVACY_REPLY
            requires_verified = True
        expires = at + CONTENT_LIFETIME
        self._session.add_all(
            [
                WebsiteMessage(
                    conversation_id=row.id,
                    command_key=command.command_key,
                    role=WebsiteMessageRole.CUSTOMER.value,
                    body=text,
                    created_at=at,
                    content_expires_at=expires,
                ),
                WebsiteMessage(
                    conversation_id=row.id,
                    command_key=f"{command.command_key}:maia",
                    role=WebsiteMessageRole.MAIA.value,
                    body=safe_reply,
                    created_at=at,
                    content_expires_at=expires,
                ),
            ]
        )
        row.hermes_session_id = reply.hermes_session_id
        row.last_activity_at = at
        await self._session.flush()
        return WebsiteConversationResult(
            row.id,
            issued,
            safe_reply,
            await self._history(row.id, at=at),
            requires_verified,
            False,
        )

    async def read(
        self, token: str | None, *, at: datetime
    ) -> tuple[uuid.UUID | None, tuple[ConversationMessageView, ...]]:
        row = await self._resolve(token)
        if row is None:
            return None, ()
        return row.id, await self._history(row.id, at=at)

    async def _resolve(
        self, token: str | None, *, lock: bool = False
    ) -> WebsiteConversationRow | None:
        if not token:
            return None
        statement = select(WebsiteConversationRow).where(
            WebsiteConversationRow.organization_id == self._actor.organization_id,
            WebsiteConversationRow.access_token_hash == token_hash(token),
        )
        return cast(
            WebsiteConversationRow | None,
            await self._session.scalar(
                statement.with_for_update() if lock else statement
            ),
        )

    async def _context(
        self,
        row: WebsiteConversationRow,
        requested: tuple[uuid.UUID, ...],
        *,
        at: datetime,
    ) -> tuple[PublicListingView, ...]:
        combined = list(dict.fromkeys([*row.listing_context, *(str(item) for item in requested)]))
        if len(combined) > MAX_CONTEXT_LISTINGS:
            raise ValueError("Comparte como máximo doce propiedades con Maia.")
        listings: list[PublicListingView] = []
        accepted: list[str] = []
        for raw in combined:
            try:
                result = await self._public.read_by_id(uuid.UUID(raw), at=at)
            except (ValueError, NotFound):
                continue
            if result.listing is not None:
                listings.append(result.listing)
                accepted.append(raw)
        row.listing_context = accepted
        return tuple(listings)

    async def _history(
        self, conversation_id: uuid.UUID, *, at: datetime
    ) -> tuple[ConversationMessageView, ...]:
        rows = list(
            await self._session.scalars(
                select(WebsiteMessage)
                .where(WebsiteMessage.conversation_id == conversation_id)
                .order_by(WebsiteMessage.created_at, WebsiteMessage.id)
            )
        )
        result: list[ConversationMessageView] = []
        for row in rows:
            if row.content_expired_at is None and row.content_expires_at <= at:
                row.body = ""
                row.content_expired_at = at
            if row.content_expired_at is None:
                result.append(ConversationMessageView(row.role, row.body, row.created_at))
        return tuple(result)

    async def _replay(
        self, conversation_id: uuid.UUID, command_key: str
    ) -> WebsiteMessage | None:
        return cast(
            WebsiteMessage | None,
            await self._session.scalar(
                select(WebsiteMessage).where(
                    WebsiteMessage.conversation_id == conversation_id,
                    WebsiteMessage.command_key == f"{command_key}:maia",
                )
            ),
        )


def _contains_pii(text: str) -> bool:
    return bool(_PHONE.search(text) or _EMAIL.search(text))
