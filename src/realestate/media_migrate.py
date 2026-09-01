"""Copy PostgreSQL-authorized Listing Media from the retired volume to S3."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.config import Settings, get_settings
from realestate.db.engine import Database
from realestate.db.models import ListingMedia
from realestate.domain.catalog.storage import MediaStorage, MediaStorageError
from realestate.infrastructure.media_storage import (
    LocalMediaStorage,
    media_storage_from_settings,
)


@dataclass(frozen=True)
class MediaMigrationReport:
    authoritative_objects: int
    copied_objects: int
    already_verified_objects: int
    copied_bytes: int


async def migrate_authoritative_media(
    session: AsyncSession,
    source: MediaStorage,
    destination: MediaStorage,
) -> MediaMigrationReport:
    """Copy only objects PostgreSQL still names, idempotently and with SHA-256."""
    rows = list(
        await session.scalars(
            select(ListingMedia)
            .where(ListingMedia.storage_deleted_at.is_(None))
            .order_by(ListingMedia.organization_id, ListingMedia.storage_key)
        )
    )
    copied = 0
    verified = 0
    copied_bytes = 0
    for row in rows:
        try:
            existing = await destination.read(row.storage_key)
        except MediaStorageError:
            existing = None
        if existing is not None and hashlib.sha256(existing).hexdigest() == row.checksum:
            verified += 1
            continue

        content = await source.read(row.storage_key)
        actual = hashlib.sha256(content).hexdigest()
        if actual != row.checksum:
            raise MediaStorageError(
                f"El objeto legado {row.storage_key!r} no coincide con PostgreSQL."
            )
        await destination.put(row.storage_key, content)
        persisted = await destination.read(row.storage_key)
        if hashlib.sha256(persisted).hexdigest() != row.checksum:
            raise MediaStorageError(
                f"El objeto migrado {row.storage_key!r} no superó la verificación."
            )
        copied += 1
        copied_bytes += len(content)

    return MediaMigrationReport(len(rows), copied, verified, copied_bytes)


async def migrate(settings: Settings, *, source_root: Path, confirmed: bool) -> MediaMigrationReport:
    if not confirmed:
        raise RuntimeError(
            "La migración necesita --confirm; no modifica PostgreSQL ni borra el volumen."
        )
    database = Database(settings.database_url)
    source = LocalMediaStorage(source_root, source_root.parent / "cache")
    destination = media_storage_from_settings(settings)
    try:
        async with database.session_scope() as session:
            return await migrate_authoritative_media(session, source, destination)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    arguments = parser.parse_args()
    report = asyncio.run(
        migrate(
            get_settings(),
            source_root=arguments.source_root,
            confirmed=arguments.confirm,
        )
    )
    print(
        "Migración verificada: "
        f"{report.authoritative_objects} objetos autoritativos; "
        f"{report.copied_objects} copiados, "
        f"{report.already_verified_objects} ya presentes; "
        f"{report.copied_bytes} bytes copiados."
    )


if __name__ == "__main__":  # pragma: no cover - exercised through Compose
    main()
