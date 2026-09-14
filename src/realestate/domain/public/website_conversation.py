"""Anonymous Website Conversation with Product-owned privacy and continuity."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    WebsiteConversation as WebsiteConversationRow,
    WebsiteConversationStatus,
    WebsiteMessage,
    WebsiteMessageRole,
    WebsiteSearchReceipt,
    WebsiteTurnRequest,
    WebsiteTurnStatus,
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
# Maia must not ask for identity, but the site prompt explicitly instructs her to
# send people to the official WhatsApp channel, and a Website Conversation exists
# to "lead toward a verified WhatsApp handoff". Matching the bare nouns therefore
# discarded exactly the answers the role is for. Only a request for a contact
# detail is refused; naming the channel is the wanted behaviour.
_MODEL_PII_REQUEST = re.compile(
    r"\b(?:d[ae]me|comp[aá]rte(?:me|nos)?|env[ií]a(?:me|nos)?|escr[ií]be(?:me|nos)?|"
    r"proporci[oó]na(?:me|nos)?|d[ée]ja(?:me|nos)?|nec[ei]sito|necesitamos|"
    r"cu[aá]l es|reg[ií]stra)\b[^.?!\n]{0,40}?"
    r"\b(?:tel[eé]fono|celular|correo|e-?mail|n[uú]mero de contacto)\b",
    re.IGNORECASE,
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
    #: Whose website this is. The responder binds a Hermes session with it, so a
    #: turn cannot attach the model's continuity to the wrong Organization.
    organization_id: uuid.UUID
    hermes_session_id: str | None
    turn_key: str
    message: str
    history: tuple[ConversationMessageView, ...]
    listings: tuple[PublicListingView, ...]


@dataclass(frozen=True)
class WebsiteReply:
    text: str
    hermes_session_id: str
    criteria: dict[str, object] = field(default_factory=dict)
    listing_ids: tuple[uuid.UUID, ...] = ()
    total: int = 0
    public_url: str | None = None
    matches: tuple[dict[str, object], ...] = ()


class WebsiteResponder(Protocol):
    async def respond(self, turn: WebsiteTurn) -> WebsiteReply: ...


@dataclass(frozen=True)
class WebsiteCommand:
    message: str
    command_key: str
    conversation_token: str | None = None
    listing_ids: tuple[uuid.UUID, ...] = ()
    sponsorship_campaign_id: uuid.UUID | None = None


@dataclass(frozen=True)
class WebsiteConversationResult:
    conversation_id: uuid.UUID
    conversation_token: str | None
    reply: str
    messages: tuple[ConversationMessageView, ...]
    requires_verified_channel: bool
    replayed: bool
    criteria: dict[str, object] = field(default_factory=dict)
    listing_ids: tuple[uuid.UUID, ...] = ()
    total: int = 0
    public_url: str | None = None
    matches: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class WebsiteTurnAccepted:
    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_token: str | None
    status: str
    replayed: bool


@dataclass(frozen=True)
class WebsiteTurnProgress:
    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    result: dict[str, object] | None
    error_message: str | None


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
        text = self._validated_message(command.message)
        row = await self._resolve(command.conversation_token, lock=True)
        issued: str | None = None
        if row is None:
            issued = f"wc-{secrets.token_urlsafe(32)}"
            row = WebsiteConversationRow(
                organization_id=self._actor.organization_id,
                access_token_hash=token_hash(issued),
                listing_context=[],
                sponsorship_campaign_id=command.sponsorship_campaign_id,
                status=WebsiteConversationStatus.OPEN.value,
                created_at=at,
                last_activity_at=at,
            )
            self._session.add(row)
            await self._session.flush()
        elif row.status == WebsiteConversationStatus.CLOSED.value:
            raise ValueError("Esta conversación terminó. Inicia una nueva.")
        elif (
            row.sponsorship_campaign_id is None
            and command.sponsorship_campaign_id is not None
        ):
            row.sponsorship_campaign_id = command.sponsorship_campaign_id

        return await self._perform(command, row=row, issued=issued, text=text, at=at)

    async def enqueue(
        self, command: WebsiteCommand, *, at: datetime
    ) -> WebsiteTurnAccepted:
        text = self._validated_message(command.message)
        issued: str | None = None
        existing = await self._session.scalar(
            select(WebsiteTurnRequest).where(
                WebsiteTurnRequest.organization_id == self._actor.organization_id,
                WebsiteTurnRequest.command_key == command.command_key,
            )
        )
        if existing is not None:
            row = await self._session.get(
                WebsiteConversationRow, existing.conversation_id
            )
            if row is None or row.organization_id != self._actor.organization_id:
                raise NotFound("No encontramos esa conversación.")
            if command.conversation_token:
                resolved = await self._resolve(command.conversation_token)
                if resolved is None or resolved.id != row.id:
                    raise NotFound("No encontramos esa conversación.")
            else:
                issued = f"wc-{secrets.token_urlsafe(32)}"
                row.access_token_hash = token_hash(issued)
            return WebsiteTurnAccepted(
                existing.id, row.id, issued, existing.status, True
            )

        row = await self._resolve(command.conversation_token, lock=True)
        if row is None:
            issued = f"wc-{secrets.token_urlsafe(32)}"
            row = WebsiteConversationRow(
                organization_id=self._actor.organization_id,
                access_token_hash=token_hash(issued),
                listing_context=[],
                sponsorship_campaign_id=command.sponsorship_campaign_id,
                status=WebsiteConversationStatus.OPEN.value,
                created_at=at,
                last_activity_at=at,
            )
            self._session.add(row)
            await self._session.flush()
        elif row.status == WebsiteConversationStatus.CLOSED.value:
            raise ValueError("Esta conversación terminó. Inicia una nueva.")

        request = WebsiteTurnRequest(
            organization_id=self._actor.organization_id,
            conversation_id=row.id,
            command_key=command.command_key,
            message=text,
            listing_ids=[str(item) for item in command.listing_ids],
            sponsorship_campaign_id=command.sponsorship_campaign_id,
            status=WebsiteTurnStatus.PENDING.value,
            attempts=0,
            created_at=at,
        )
        self._session.add(request)
        await self._session.flush()
        return WebsiteTurnAccepted(
            request.id, row.id, issued, request.status, False
        )

    async def progress(
        self, turn_id: uuid.UUID, token: str | None
    ) -> WebsiteTurnProgress:
        conversation = await self._resolve(token)
        if conversation is None:
            raise NotFound("No encontramos esa conversación.")
        request = await self._session.scalar(
            select(WebsiteTurnRequest).where(
                WebsiteTurnRequest.organization_id == self._actor.organization_id,
                WebsiteTurnRequest.conversation_id == conversation.id,
                WebsiteTurnRequest.id == turn_id,
            )
        )
        if request is None:
            raise NotFound("No encontramos ese turno.")
        return WebsiteTurnProgress(
            request.id,
            request.conversation_id,
            request.status,
            dict(request.result) if request.result is not None else None,
            request.error_message,
        )

    async def perform_request(
        self, request: WebsiteTurnRequest, *, at: datetime
    ) -> WebsiteConversationResult:
        row = await self._session.scalar(
            select(WebsiteConversationRow).where(
                WebsiteConversationRow.organization_id == self._actor.organization_id,
                WebsiteConversationRow.id == request.conversation_id,
            )
        )
        if row is None:
            raise NotFound("No encontramos esa conversación.")
        if row.status == WebsiteConversationStatus.CLOSED.value:
            raise ValueError("Esta conversación terminó. Inicia una nueva.")
        return await self._perform(
            WebsiteCommand(
                message=request.message,
                command_key=request.command_key,
                listing_ids=tuple(uuid.UUID(item) for item in request.listing_ids),
                sponsorship_campaign_id=request.sponsorship_campaign_id,
            ),
            row=row,
            issued=None,
            text=request.message,
            at=at,
        )

    async def _perform(
        self,
        command: WebsiteCommand,
        *,
        row: WebsiteConversationRow,
        issued: str | None,
        text: str,
        at: datetime,
    ) -> WebsiteConversationResult:

        replay = await self._replay(row.id, command.command_key)
        if replay is not None:
            search = await self._search_receipt(
                row.organization_id, command.command_key
            )
            return WebsiteConversationResult(
                row.id,
                issued,
                replay.body,
                await self._history(row.id, at=at),
                False,
                True,
                dict(search.criteria) if search is not None else {},
                (
                    tuple(uuid.UUID(item) for item in search.listing_ids)
                    if search is not None
                    else ()
                ),
                search.total if search is not None else 0,
                search.public_url if search is not None else None,
                (
                    tuple(dict(item) for item in search.response.get("matches", []))
                    if search is not None
                    else ()
                ),
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
                organization_id=row.organization_id,
                hermes_session_id=row.hermes_session_id,
                turn_key=command.command_key,
                message=text,
                history=history,
                listings=listings,
            )
        )
        safe_reply = reply.text.strip()
        requires_verified = False
        if (
            not safe_reply
            or _contains_pii(safe_reply)
            or _MODEL_PII_REQUEST.search(safe_reply)
        ):
            safe_reply = _PRIVACY_REPLY
            requires_verified = True
        expires = at + CONTENT_LIFETIME
        self._session.add_all(
            [
                WebsiteMessage(
                    organization_id=row.organization_id,
                    conversation_id=row.id,
                    command_key=command.command_key,
                    role=WebsiteMessageRole.CUSTOMER.value,
                    body=text,
                    created_at=at,
                    content_expires_at=expires,
                ),
                WebsiteMessage(
                    organization_id=row.organization_id,
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
            reply.criteria,
            reply.listing_ids,
            reply.total,
            reply.public_url,
            reply.matches,
        )

    @staticmethod
    def _validated_message(message: str) -> str:
        text = message.strip()
        if not text:
            raise ValueError("Escribe un mensaje para Maia.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError("El mensaje es demasiado largo.")
        return text

    async def read(
        self, token: str | None, *, at: datetime
    ) -> tuple[uuid.UUID | None, tuple[ConversationMessageView, ...]]:
        row = await self._resolve(token)
        if row is None:
            return None, ()
        return row.id, await self._history(row.id, at=at)

    async def close(
        self, token: str | None, *, at: datetime, delete_content: bool
    ) -> bool:
        """End visible continuity and optionally erase retained message bodies."""

        row = await self._resolve(token, lock=True)
        if row is None:
            return False
        row.status = WebsiteConversationStatus.CLOSED.value
        row.last_activity_at = at
        await self._session.execute(
            update(WebsiteTurnRequest)
            .where(
                WebsiteTurnRequest.organization_id == self._actor.organization_id,
                WebsiteTurnRequest.conversation_id == row.id,
                WebsiteTurnRequest.status == WebsiteTurnStatus.PENDING.value,
            )
            .values(
                status=WebsiteTurnStatus.FAILED.value,
                error_message="La conversación terminó antes de responder.",
                completed_at=at,
            )
        )
        if delete_content:
            await self._session.execute(
                update(WebsiteMessage)
                .where(
                    WebsiteMessage.organization_id == self._actor.organization_id,
                    WebsiteMessage.conversation_id == row.id,
                )
                .values(body="", content_expired_at=at)
            )
        return True

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

    async def _search_receipt(
        self, organization_id: uuid.UUID, turn_key: str
    ) -> WebsiteSearchReceipt | None:
        return cast(
            WebsiteSearchReceipt | None,
            await self._session.scalar(
                select(WebsiteSearchReceipt).where(
                    WebsiteSearchReceipt.organization_id == organization_id,
                    WebsiteSearchReceipt.turn_key == turn_key,
                )
            ),
        )


def _contains_pii(text: str) -> bool:
    return bool(_PHONE.search(text) or _EMAIL.search(text))
