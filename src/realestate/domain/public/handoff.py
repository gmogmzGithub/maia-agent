"""Opaque, expiring, single-use continuity between website and WhatsApp."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ChannelHandoff as ChannelHandoffRow,
    ChannelHandoffPurpose,
    Contact,
    ContactChannelIdentity,
    Conversation,
    SavedCollection,
    WebsiteConversation as WebsiteConversationRow,
    WebsiteConversationStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, CommercialError, NotFound
from realestate.domain.public.listing import PublicListing
from realestate.domain.public.saved import SavedCollections, token_hash

HANDOFF_LIFETIME = timedelta(minutes=30)
PROTECTION_LIFETIME = timedelta(hours=24)
_REFERENCE = re.compile(r"\bLAR-[A-Fa-f0-9]{48}\b")


class HandoffExpired(CommercialError):
    pass


class HandoffReplay(CommercialError):
    pass


class HandoffIdentityMismatch(CommercialError):
    pass


@dataclass(frozen=True)
class CreateHandoff:
    purpose: ChannelHandoffPurpose
    command_key: str
    website_conversation_id: uuid.UUID | None = None
    saved_collection_id: uuid.UUID | None = None
    listing_id: uuid.UUID | None = None
    expected_contact_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreatedHandoff:
    handoff_id: uuid.UUID
    token: str
    expires_at: datetime
    replayed: bool


@dataclass(frozen=True)
class ResolvedHandoff:
    handoff_id: uuid.UUID
    purpose: ChannelHandoffPurpose
    listing_id: uuid.UUID | None
    website_conversation_id: uuid.UUID | None
    saved_collection_id: uuid.UUID | None


def extract_handoff_reference(text: str | None) -> str | None:
    match = _REFERENCE.search(text or "")
    return match.group(0).upper() if match else None


class ChannelHandoff:
    """Hide token safety, context validation, replay and collection merging."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def create(self, command: CreateHandoff, *, at: datetime) -> CreatedHandoff:
        await self._validate_context(command, at=at)
        raw = self._deterministic_token(command)
        existing = await self._session.scalar(
            select(ChannelHandoffRow).where(
                ChannelHandoffRow.organization_id == self._actor.organization_id,
                ChannelHandoffRow.token_hash == token_hash(raw),
            )
        )
        if existing is not None:
            return CreatedHandoff(existing.id, raw, existing.expires_at, True)
        lifetime = (
            PROTECTION_LIFETIME
            if command.purpose is ChannelHandoffPurpose.SAVED_COLLECTION_PROTECTION
            else HANDOFF_LIFETIME
        )
        row = ChannelHandoffRow(
            organization_id=self._actor.organization_id,
            token_hash=token_hash(raw),
            purpose=command.purpose.value,
            website_conversation_id=command.website_conversation_id,
            saved_collection_id=command.saved_collection_id,
            listing_id=command.listing_id,
            expected_contact_id=command.expected_contact_id,
            created_at=at,
            expires_at=at + lifetime,
        )
        self._session.add(row)
        if command.website_conversation_id is not None:
            conversation = await self._session.get(
                WebsiteConversationRow, command.website_conversation_id
            )
            assert conversation is not None
            conversation.status = WebsiteConversationStatus.HANDOFF_PENDING.value
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="CreateChannelHandoff",
            subject_type="ChannelHandoff",
            subject_id=str(row.id),
            details={"purpose": command.purpose.value},
            commit=False,
        )
        await self._session.flush()
        return CreatedHandoff(row.id, raw, row.expires_at, False)

    async def resolve(
        self,
        token: str,
        *,
        verified_contact_id: uuid.UUID,
        whatsapp_conversation_id: uuid.UUID | None,
        at: datetime,
    ) -> ResolvedHandoff:
        contact = await self._session.get(Contact, verified_contact_id)
        if contact is None or contact.organization_id != self._actor.organization_id:
            raise NotFound("No encontramos la identidad verificada.")
        row = await self._session.scalar(
            select(ChannelHandoffRow)
            .where(
                ChannelHandoffRow.organization_id == self._actor.organization_id,
                ChannelHandoffRow.token_hash == token_hash(token.upper()),
            )
            .with_for_update()
        )
        if row is None:
            raise NotFound("La referencia de continuidad no existe.")
        if row.expires_at <= at:
            raise HandoffExpired("La referencia de continuidad ya venció.")
        if row.consumed_at is not None:
            raise HandoffReplay("La referencia de continuidad ya fue utilizada.")
        if (
            row.expected_contact_id is not None
            and row.expected_contact_id != verified_contact_id
        ):
            raise HandoffIdentityMismatch(
                "La referencia pertenece a otra identidad verificada."
            )
        if row.saved_collection_id is not None:
            protected = await SavedCollections(self._session, self._actor).protect(
                row.saved_collection_id, verified_contact_id, at=at
            )
            row.saved_collection_id = protected.id
        if row.website_conversation_id is not None:
            website = await self._session.get(
                WebsiteConversationRow, row.website_conversation_id
            )
            if website is None:
                raise NotFound("La conversación del sitio ya no está disponible.")
            website.verified_contact_id = verified_contact_id
            website.status = WebsiteConversationStatus.VERIFIED.value
            website.last_activity_at = at
        if whatsapp_conversation_id is not None and row.listing_id is not None:
            whatsapp = await self._session.get(Conversation, whatsapp_conversation_id)
            if whatsapp is None or whatsapp.organization_id != self._actor.organization_id:
                raise NotFound("La conversación verificada no existe.")
            conversation_contact_id = await self._session.scalar(
                select(ContactChannelIdentity.contact_id).where(
                    ContactChannelIdentity.organization_id
                    == self._actor.organization_id,
                    ContactChannelIdentity.lead_id == whatsapp.lead_id,
                )
            )
            if conversation_contact_id != verified_contact_id:
                raise HandoffIdentityMismatch(
                    "La conversación no pertenece a la identidad verificada."
                )
            listing = await PublicListing(self._session, self._actor).read_by_id(
                row.listing_id, at=at
            )
            if listing.listing is None:
                raise NotFound("La propiedad ya no está disponible.")
            whatsapp.property_uuid = listing.listing.property_id
        row.consumed_at = at
        row.consumed_by_contact_id = verified_contact_id
        await record_audit(
            self._session,
            actor_type="Contact",
            actor_id=str(verified_contact_id),
            action="ResolveChannelHandoff",
            subject_type="ChannelHandoff",
            subject_id=str(row.id),
            details={"purpose": row.purpose},
            commit=False,
        )
        await self._session.flush()
        return ResolvedHandoff(
            handoff_id=row.id,
            purpose=ChannelHandoffPurpose(row.purpose),
            listing_id=row.listing_id,
            website_conversation_id=row.website_conversation_id,
            saved_collection_id=row.saved_collection_id,
        )

    async def _validate_context(
        self, command: CreateHandoff, *, at: datetime
    ) -> None:
        if not any(
            (
                command.website_conversation_id,
                command.saved_collection_id,
                command.listing_id,
            )
        ):
            raise ValueError("La continuidad necesita contexto.")
        if command.website_conversation_id is not None:
            row = await self._session.get(
                WebsiteConversationRow, command.website_conversation_id
            )
            if row is None or row.organization_id != self._actor.organization_id:
                raise NotFound("La conversación del sitio no existe.")
        if command.saved_collection_id is not None:
            collection = await self._session.get(
                SavedCollection, command.saved_collection_id
            )
            if (
                collection is None
                or collection.organization_id != self._actor.organization_id
                or collection.deleted_at is not None
            ):
                raise NotFound("La colección ya no está disponible.")
        if command.listing_id is not None:
            listing = await PublicListing(self._session, self._actor).read_by_id(
                command.listing_id, at=at
            )
            if listing.listing is None:
                raise NotFound("La propiedad ya no está disponible.")
        if command.expected_contact_id is not None:
            contact = await self._session.get(Contact, command.expected_contact_id)
            if contact is None or contact.organization_id != self._actor.organization_id:
                raise NotFound("La identidad esperada no existe.")

    def _deterministic_token(self, command: CreateHandoff) -> str:
        material = ":".join(
            (
                str(self._actor.organization_id),
                command.command_key,
                command.purpose.value,
                str(command.website_conversation_id or ""),
                str(command.saved_collection_id or ""),
                str(command.listing_id or ""),
                str(command.expected_contact_id or ""),
            )
        )
        return f"LAR-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:48]}".upper()
