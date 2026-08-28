"""Administrator-owned Listing Media lifecycle (ADR-0038)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import CatalogListing, ListingAuthority, ListingMedia
from realestate.domain.audit import record_audit
from realestate.domain.catalog.storage import MediaStorage, MediaStorageError
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)
from realestate.domain.commercial.idempotency import CommercialCommands

MAX_MEDIA_BYTES = 20 * 1024 * 1024

_EXTENSIONS = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}
_STORAGE_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MediaCleanupPending(CommercialError):
    message = (
        "El medio ya quedó revocado y fuera de las proyecciones públicas, pero "
        "falta terminar la limpieza de almacenamiento o caché. Reintenta la misma "
        "operación."
    )


@dataclass(frozen=True)
class AddMedia:
    listing_id: uuid.UUID
    original_filename: str
    content_type: str
    content: bytes
    provenance: str
    authority: ListingAuthority
    authority_evidence: str | None
    is_cover: bool
    sort_order: int
    space_group: str | None
    high_resolution: bool
    cache_keys: tuple[str, ...]
    command_key: str


@dataclass(frozen=True)
class MediaPlacement:
    media_id: uuid.UUID
    sort_order: int
    space_group: str | None


@dataclass(frozen=True)
class ArrangeMedia:
    listing_id: uuid.UUID
    cover_id: uuid.UUID
    placements: tuple[MediaPlacement, ...]
    command_key: str


@dataclass(frozen=True)
class RevokeMedia:
    media_id: uuid.UUID
    command_key: str


Command = AddMedia | ArrangeMedia | RevokeMedia


@dataclass(frozen=True)
class MediaRecorded:
    media_id: uuid.UUID
    listing_id: uuid.UUID
    replayed: bool
    cleanup_complete: bool = True


def _now() -> datetime:
    return datetime.now(tz=UTC)


class MediaAdministration:
    """Media commands plus recoverable storage/cache side effects.

    Unlike ordinary catalog commands, each operation commits here.  A media
    revocation must become publicly invisible before remote cleanup begins; a
    retry after restart resumes whichever idempotent cleanup stamp is missing.
    """

    def __init__(self, session: AsyncSession, storage: MediaStorage) -> None:
        self._session = session
        self._storage = storage
        self._commands = CommercialCommands(session)

    async def record(self, actor: Actor, command: Command) -> MediaRecorded:
        actor.require_administrator()
        if isinstance(command, AddMedia):
            return await self._add(actor, command)
        if isinstance(command, ArrangeMedia):
            return await self._arrange(actor, command)
        return await self._revoke(actor, command)

    async def _add(self, actor: Actor, command: AddMedia) -> MediaRecorded:
        listing = await self._listing(actor, command.listing_id, lock=True)
        checksum = self._validate_upload(command)
        media_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"maia-media:{actor.organization_id}:{command.command_key}",
        )
        storage_key = (
            f"{actor.organization_id}/{listing.id}/{media_id}"
            f"{_STORAGE_EXTENSION[command.content_type]}"
        )
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="AddListingMedia",
            subject_type="ListingMedia",
            subject_id=str(media_id),
            payload={
                "listing_id": listing.id,
                "filename": command.original_filename,
                "content_type": command.content_type,
                "checksum": checksum,
                "provenance": command.provenance,
                "authority": command.authority.value,
                "authority_evidence": command.authority_evidence,
                "is_cover": command.is_cover,
                "sort_order": command.sort_order,
                "space_group": command.space_group,
                "high_resolution": command.high_resolution,
                "cache_keys": command.cache_keys,
            },
        )
        if replayed:
            existing = await self._session.get(ListingMedia, media_id)
            if existing is None:
                raise InvalidTransition(
                    "La operación existe pero su medio no está disponible."
                )
            return MediaRecorded(existing.id, existing.listing_id, True)
        if command.authority is ListingAuthority.AUTHORIZED and not (
            command.authority_evidence or ""
        ).strip():
            raise InvalidTransition(
                "Registra la evidencia de autoridad para usar esta fotografía."
            )
        if command.sort_order < 0:
            raise InvalidTransition("El orden de la fotografía no puede ser negativo.")
        provenance = command.provenance.strip()
        if not provenance:
            raise InvalidTransition("Registra la procedencia de la fotografía.")

        stored = False
        try:
            await self._storage.put(storage_key, command.content)
            stored = True
            if command.is_cover:
                current = await self._session.scalar(
                    select(ListingMedia)
                    .where(
                        ListingMedia.listing_id == listing.id,
                        ListingMedia.is_cover.is_(True),
                        ListingMedia.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                if current is not None:
                    current.is_cover = False
            row = ListingMedia(
                id=media_id,
                organization_id=actor.organization_id,
                listing_id=listing.id,
                storage_key=storage_key,
                original_filename=command.original_filename.strip(),
                content_type=command.content_type,
                byte_size=len(command.content),
                checksum=checksum,
                provenance=provenance,
                authority=command.authority.value,
                authority_evidence=(command.authority_evidence or "").strip() or None,
                is_cover=command.is_cover,
                sort_order=command.sort_order,
                space_group=(command.space_group or "").strip() or None,
                high_resolution=command.high_resolution,
                cache_keys=list(command.cache_keys),
                uploaded_by=actor.member_id,
            )
            self._session.add(row)
            await record_audit(
                self._session,
                actor_type=actor.actor_type,
                actor_id=actor.label,
                action="AddListingMedia",
                subject_type="ListingMedia",
                subject_id=str(row.id),
                details={
                    "listing_id": str(listing.id),
                    "content_type": row.content_type,
                    "checksum": row.checksum,
                    "authority": row.authority,
                    "is_cover": row.is_cover,
                    "sort_order": row.sort_order,
                    "space_group": row.space_group,
                },
                commit=False,
            )
            await self._session.commit()
            return MediaRecorded(row.id, row.listing_id, False)
        except IntegrityError as exc:
            await self._session.rollback()
            if stored:
                await self._storage.delete(storage_key)
            raise InvalidTransition(
                "La fotografía duplica el orden, contenido o portada de otra activa."
            ) from exc
        except Exception:
            await self._session.rollback()
            if stored:
                await self._storage.delete(storage_key)
            raise

    async def _arrange(
        self, actor: Actor, command: ArrangeMedia
    ) -> MediaRecorded:
        listing = await self._listing(actor, command.listing_id, lock=True)
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="ArrangeListingMedia",
            subject_type="CatalogListing",
            subject_id=str(listing.id),
            payload={
                "cover_id": command.cover_id,
                "placements": [
                    row.__dict__
                    for row in sorted(
                        command.placements, key=lambda placement: str(placement.media_id)
                    )
                ],
            },
        )
        rows = list(
            await self._session.scalars(
                select(ListingMedia)
                .where(
                    ListingMedia.listing_id == listing.id,
                    ListingMedia.revoked_at.is_(None),
                )
                .with_for_update()
            )
        )
        if replayed:
            return MediaRecorded(command.cover_id, listing.id, True)
        active_ids = {row.id for row in rows}
        requested_ids = {row.media_id for row in command.placements}
        orders = [row.sort_order for row in command.placements]
        if active_ids != requested_ids or command.cover_id not in active_ids:
            raise InvalidTransition(
                "Incluye exactamente todas las fotografías activas y una portada."
            )
        if len(orders) != len(set(orders)) or any(order < 0 for order in orders):
            raise InvalidTransition("Cada fotografía necesita un orden único válido.")

        by_id = {row.id: row for row in rows}
        # Clear unique slots before a swap (1<->2); the transaction keeps the
        # temporary values invisible.
        for offset, row in enumerate(rows, start=1):
            row.sort_order = 1_000_000 + offset
            row.is_cover = False
        await self._session.flush()
        for placement in command.placements:
            row = by_id[placement.media_id]
            row.sort_order = placement.sort_order
            row.space_group = (placement.space_group or "").strip() or None
            row.is_cover = row.id == command.cover_id
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ArrangeListingMedia",
            subject_type="CatalogListing",
            subject_id=str(listing.id),
            details={
                "cover_id": str(command.cover_id),
                "order": [str(row.media_id) for row in command.placements],
                "groups": {
                    str(row.media_id): row.space_group for row in command.placements
                },
            },
            commit=False,
        )
        await self._session.commit()
        return MediaRecorded(command.cover_id, listing.id, False)

    async def _revoke(self, actor: Actor, command: RevokeMedia) -> MediaRecorded:
        row = await self._session.scalar(
            select(ListingMedia)
            .where(ListingMedia.id == command.media_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa fotografía.")
        actor.require_same_organization(row.organization_id)
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="RevokeListingMedia",
            subject_type="ListingMedia",
            subject_id=str(row.id),
            payload={"media_id": row.id},
        )
        if row.revoked_at is None:
            row.authority = ListingAuthority.REVOKED.value
            row.revoked_at = _now()
            row.revoked_by = actor.member_id
            row.is_cover = False
            await record_audit(
                self._session,
                actor_type=actor.actor_type,
                actor_id=actor.label,
                action="RevokeListingMedia",
                subject_type="ListingMedia",
                subject_id=str(row.id),
                details={
                    "listing_id": str(row.listing_id),
                    "storage_cleanup": "Pending",
                    "cache_cleanup": "Pending",
                },
                commit=False,
            )
            # Public eligibility stops here, before a storage provider is
            # contacted.  A crash after this commit resumes cleanup on replay.
            await self._session.commit()

        try:
            if row.storage_deleted_at is None:
                await self._storage.delete(row.storage_key)
                row.storage_deleted_at = _now()
                await self._session.commit()
            if row.cache_purged_at is None:
                await self._storage.purge_cache(tuple(row.cache_keys))
                row.cache_purged_at = _now()
                await self._session.commit()
        except MediaStorageError as exc:
            await self._session.rollback()
            raise MediaCleanupPending() from exc
        return MediaRecorded(row.id, row.listing_id, replayed)

    async def _listing(
        self, actor: Actor, listing_id: uuid.UUID, *, lock: bool
    ) -> CatalogListing:
        statement = select(CatalogListing).where(CatalogListing.id == listing_id)
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFound()
        actor.require_same_organization(row.organization_id)
        return row

    @staticmethod
    def _validate_upload(command: AddMedia) -> str:
        content_type = command.content_type
        if content_type not in _EXTENSIONS:
            raise InvalidTransition("Sólo se aceptan fotografías JPG, PNG o WebP.")
        filename = command.original_filename.strip().casefold()
        if not filename.endswith(_EXTENSIONS[content_type]):
            raise InvalidTransition(
                "La extensión del archivo no coincide con su tipo de imagen."
            )
        content = command.content
        if not content or len(content) > MAX_MEDIA_BYTES:
            raise InvalidTransition(
                f"La fotografía debe pesar entre 1 byte y {MAX_MEDIA_BYTES} bytes."
            )
        valid_signature = (
            (content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
            or (
                content_type == "image/png"
                and content.startswith(b"\x89PNG\r\n\x1a\n")
            )
            or (
                content_type == "image/webp"
                and len(content) >= 12
                and content.startswith(b"RIFF")
                and content[8:12] == b"WEBP"
            )
        )
        if not valid_signature:
            raise InvalidTransition(
                "El contenido no coincide con una imagen JPG, PNG o WebP válida."
            )
        return hashlib.sha256(content).hexdigest()
