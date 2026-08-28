"""Progressive, server-backed Saved Collections (ADR-0040)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    SavedCollection,
    SavedCollectionItem,
    SharedSelection,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.public.catalog import PublicListingView
from realestate.domain.public.listing import PublicListing

ANONYMOUS_COLLECTION_LIFETIME = timedelta(days=365)
SHARED_SELECTION_LIFETIME = timedelta(days=30)


class SavedAction(str, Enum):
    ADD = "Add"
    REMOVE = "Remove"
    EMPTY = "Empty"
    DELETE = "Delete"
    SHARE = "Share"


@dataclass(frozen=True)
class SavedCommand:
    action: SavedAction
    command_key: str
    collection_token: str | None = None
    listing_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SavedItemView:
    listing_id: uuid.UUID
    slug: str
    title: str
    public_location: str | None
    available: bool
    listing: PublicListingView | None
    saved_at: datetime


@dataclass(frozen=True)
class SavedResult:
    collection_id: uuid.UUID | None
    collection_token: str | None
    protected: bool
    changed: bool
    items: tuple[SavedItemView, ...]
    shared_token: str | None = None


@dataclass(frozen=True)
class SharedSelectionView:
    items: tuple[SavedItemView, ...]
    expires_at: datetime


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token(prefix: str) -> str:
    return f"{prefix}-{secrets.token_urlsafe(32)}"


class SavedCollections:
    """Hide cookies, merging, expiry, idempotency and withdrawn-item history."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor
        self._commands = CommercialCommands(session)
        self._public = PublicListing(session, actor)

    async def record(self, command: SavedCommand, *, at: datetime) -> SavedResult:
        token = command.collection_token
        collection = await self._resolve(token, at=at, lock=True) if token else None
        issued: str | None = None
        if collection is None:
            if command.action not in {SavedAction.ADD}:
                return SavedResult(None, None, False, False, ())
            issued = _new_token("sc")
            collection = SavedCollection(
                organization_id=self._actor.organization_id,
                access_token_hash=token_hash(issued),
                last_activity_at=at,
                expires_at=at + ANONYMOUS_COLLECTION_LIFETIME,
            )
            self._session.add(collection)
            await self._session.flush()

        replayed = await self._commands.claim(
            self._actor,
            command_key=command.command_key,
            operation=f"SavedCollection{command.action.value}",
            subject_type="SavedCollection",
            subject_id=str(collection.id),
            payload={"listing_id": command.listing_id},
        )
        changed = False
        shared_token: str | None = None
        if not replayed:
            changed, shared_token = await self._apply(collection, command, at=at)
        elif command.action is SavedAction.SHARE:
            shared_token = self._selection_token(collection, command.command_key)
        collection.last_activity_at = at
        if collection.protected_contact_id is None:
            collection.expires_at = at + ANONYMOUS_COLLECTION_LIFETIME
        await self._session.flush()
        return SavedResult(
            collection_id=collection.id,
            collection_token=issued,
            protected=collection.protected_contact_id is not None,
            changed=changed,
            items=await self._items(collection, at=at),
            shared_token=shared_token,
        )

    async def read(self, token: str | None, *, at: datetime) -> SavedResult:
        collection = await self._resolve(token, at=at) if token else None
        if collection is None:
            return SavedResult(None, None, False, False, ())
        return SavedResult(
            collection_id=collection.id,
            collection_token=None,
            protected=collection.protected_contact_id is not None,
            changed=False,
            items=await self._items(collection, at=at),
        )

    async def protect(
        self, collection_id: uuid.UUID, contact_id: uuid.UUID, *, at: datetime
    ) -> SavedCollection:
        source = await self._session.scalar(
            select(SavedCollection)
            .where(
                SavedCollection.id == collection_id,
                SavedCollection.organization_id == self._actor.organization_id,
            )
            .with_for_update()
        )
        if source is None or source.deleted_at is not None:
            raise NotFound("La colección ya no está disponible.")
        existing = await self._session.scalar(
            select(SavedCollection)
            .where(
                SavedCollection.organization_id == self._actor.organization_id,
                SavedCollection.protected_contact_id == contact_id,
                SavedCollection.deleted_at.is_(None),
                SavedCollection.merged_into_id.is_(None),
            )
            .with_for_update()
        )
        if existing is None or existing.id == source.id:
            source.protected_contact_id = contact_id
            source.expires_at = None
            source.last_activity_at = at
            await self._session.flush()
            return source

        items = list(
            await self._session.scalars(
                select(SavedCollectionItem).where(
                    SavedCollectionItem.collection_id == source.id
                )
            )
        )
        existing_ids = set(
            await self._session.scalars(
                select(SavedCollectionItem.listing_id).where(
                    SavedCollectionItem.collection_id == existing.id
                )
            )
        )
        for item in items:
            if item.listing_id in existing_ids:
                await self._session.delete(item)
            else:
                item.collection_id = existing.id
        source.merged_into_id = existing.id
        source.deleted_at = at
        existing.last_activity_at = at
        await self._session.flush()
        return existing

    async def shared(self, token: str, *, at: datetime) -> SharedSelectionView:
        row = await self._session.scalar(
            select(SharedSelection).where(
                SharedSelection.organization_id == self._actor.organization_id,
                SharedSelection.access_token_hash == token_hash(token),
            )
        )
        if row is None or row.revoked_at is not None or row.expires_at <= at:
            raise NotFound("Esta selección ya no está disponible.")
        items: list[SavedItemView] = []
        for snapshot in row.snapshot:
            listing_id = uuid.UUID(str(snapshot["listing_id"]))
            public = await self._safe_listing(listing_id, at=at)
            items.append(
                SavedItemView(
                    listing_id=listing_id,
                    slug=str(snapshot["slug"]),
                    title=str(snapshot["title"]),
                    public_location=(
                        str(snapshot["public_location"])
                        if snapshot.get("public_location")
                        else None
                    ),
                    available=public is not None,
                    listing=public,
                    saved_at=row.created_at,
                )
            )
        return SharedSelectionView(tuple(items), row.expires_at)

    async def _apply(
        self, collection: SavedCollection, command: SavedCommand, *, at: datetime
    ) -> tuple[bool, str | None]:
        if command.action in {SavedAction.ADD, SavedAction.REMOVE}:
            if command.listing_id is None:
                raise ValueError("La propiedad es obligatoria para guardar o quitar.")
            if command.action is SavedAction.ADD:
                public = await self._public.read_by_id(command.listing_id, at=at)
                if public.listing is None:
                    raise NotFound("La propiedad ya no está disponible.")
                existing = await self._session.scalar(
                    select(SavedCollectionItem).where(
                        SavedCollectionItem.collection_id == collection.id,
                        SavedCollectionItem.listing_id == command.listing_id,
                    )
                )
                if existing is not None:
                    return False, None
                self._session.add(
                    SavedCollectionItem(
                        collection_id=collection.id,
                        listing_id=command.listing_id,
                        slug_snapshot=public.listing.slug,
                        title_snapshot=public.listing.title,
                        location_snapshot=public.listing.public_location,
                        saved_at=at,
                    )
                )
                return True, None
            existing = await self._session.scalar(
                select(SavedCollectionItem).where(
                    SavedCollectionItem.collection_id == collection.id,
                    SavedCollectionItem.listing_id == command.listing_id,
                )
            )
            if existing is None:
                return False, None
            await self._session.delete(existing)
            return True, None
        if command.action is SavedAction.EMPTY:
            existing_items = await self._item_rows(collection)
            await self._session.execute(
                delete(SavedCollectionItem).where(
                    SavedCollectionItem.collection_id == collection.id
                )
            )
            return bool(existing_items), None
        if command.action is SavedAction.DELETE:
            await self._session.execute(
                delete(SavedCollectionItem).where(
                    SavedCollectionItem.collection_id == collection.id
                )
            )
            collection.deleted_at = at
            return True, None
        if command.action is SavedAction.SHARE:
            items = await self._item_rows(collection)
            raw = self._selection_token(collection, command.command_key)
            self._session.add(
                SharedSelection(
                    organization_id=self._actor.organization_id,
                    collection_id=collection.id,
                    access_token_hash=token_hash(raw),
                    snapshot=[
                        {
                            "listing_id": str(item.listing_id),
                            "slug": item.slug_snapshot,
                            "title": item.title_snapshot,
                            "public_location": item.location_snapshot,
                        }
                        for item in items
                    ],
                    created_at=at,
                    expires_at=at + SHARED_SELECTION_LIFETIME,
                )
            )
            return True, raw
        raise ValueError("La acción de guardado no es válida.")

    async def _resolve(
        self, token: str | None, *, at: datetime, lock: bool = False
    ) -> SavedCollection | None:
        if not token:
            return None
        statement = select(SavedCollection).where(
            SavedCollection.organization_id == self._actor.organization_id,
            SavedCollection.access_token_hash == token_hash(token),
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        for _ in range(4):
            if row is None or row.deleted_at is not None and row.merged_into_id is None:
                return None
            if row.merged_into_id is None:
                break
            follow = select(SavedCollection).where(
                SavedCollection.id == row.merged_into_id,
                SavedCollection.organization_id == self._actor.organization_id,
            )
            row = await self._session.scalar(follow.with_for_update() if lock else follow)
        else:
            return None
        if row is None or (
            row.protected_contact_id is None
            and row.expires_at is not None
            and row.expires_at <= at
        ):
            return None
        return row

    async def _items(
        self, collection: SavedCollection, *, at: datetime
    ) -> tuple[SavedItemView, ...]:
        result: list[SavedItemView] = []
        for item in await self._item_rows(collection):
            public = await self._safe_listing(item.listing_id, at=at)
            result.append(
                SavedItemView(
                    listing_id=item.listing_id,
                    slug=item.slug_snapshot,
                    title=item.title_snapshot,
                    public_location=item.location_snapshot,
                    available=public is not None,
                    listing=public,
                    saved_at=item.saved_at,
                )
            )
        return tuple(result)

    async def _item_rows(
        self, collection: SavedCollection
    ) -> tuple[SavedCollectionItem, ...]:
        return tuple(
            await self._session.scalars(
                select(SavedCollectionItem)
                .where(SavedCollectionItem.collection_id == collection.id)
                .order_by(SavedCollectionItem.saved_at, SavedCollectionItem.id)
            )
        )

    async def _safe_listing(
        self, listing_id: uuid.UUID, *, at: datetime
    ) -> PublicListingView | None:
        try:
            result = await self._public.read_by_id(listing_id, at=at)
        except NotFound:
            return None
        return result.listing

    @staticmethod
    def _selection_token(collection: SavedCollection, command_key: str) -> str:
        return f"ss-{token_hash(f'{collection.access_token_hash}:{command_key}')}"
