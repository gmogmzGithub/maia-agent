"""The retired filesystem volume migrates by PostgreSQL authority, not directory scan."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
import uuid

import pytest

from realestate.domain.catalog.storage import MediaStorageError
from realestate.media_migrate import migrate_authoritative_media
from tests.fixtures.media import InMemoryMediaStorage


@dataclass
class MediaRow:
    organization_id: uuid.UUID
    storage_key: str
    checksum: str


class FakeSession:
    def __init__(self, rows: list[MediaRow]) -> None:
        self.rows = rows

    async def scalars(self, statement: object) -> list[MediaRow]:
        return self.rows


async def test_migration_copies_only_authoritative_rows_and_verifies_bytes() -> None:
    organization_id = uuid.uuid4()
    content = b"authoritative photograph"
    key = f"{organization_id}/listing/photo.jpg"
    row = MediaRow(organization_id, key, hashlib.sha256(content).hexdigest())
    source = InMemoryMediaStorage()
    source.objects[key] = content
    source.objects["orphan/photo.jpg"] = b"must not migrate"
    destination = InMemoryMediaStorage()

    report = await migrate_authoritative_media(
        FakeSession([row]),  # type: ignore[arg-type]
        source,
        destination,
    )

    assert report.authoritative_objects == 1
    assert report.copied_objects == 1
    assert report.copied_bytes == len(content)
    assert destination.objects == {key: content}


async def test_migration_is_idempotent_when_destination_checksum_matches() -> None:
    organization_id = uuid.uuid4()
    content = b"already copied"
    key = f"{organization_id}/listing/photo.jpg"
    row = MediaRow(organization_id, key, hashlib.sha256(content).hexdigest())
    source = InMemoryMediaStorage()
    destination = InMemoryMediaStorage()
    destination.objects[key] = content

    report = await migrate_authoritative_media(
        FakeSession([row]),  # type: ignore[arg-type]
        source,
        destination,
    )

    assert report.copied_objects == 0
    assert report.already_verified_objects == 1


async def test_migration_refuses_a_source_that_disagrees_with_postgresql() -> None:
    organization_id = uuid.uuid4()
    key = f"{organization_id}/listing/photo.jpg"
    row = MediaRow(organization_id, key, hashlib.sha256(b"expected").hexdigest())
    source = InMemoryMediaStorage()
    source.objects[key] = b"different"

    with pytest.raises(MediaStorageError, match="no coincide con PostgreSQL"):
        await migrate_authoritative_media(
            FakeSession([row]),  # type: ignore[arg-type]
            source,
            InMemoryMediaStorage(),
        )
