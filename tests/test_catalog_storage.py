"""Contract of the local Listing Media storage adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from realestate.domain.catalog.storage import LocalMediaStorage, MediaStorageError


async def test_local_storage_put_delete_and_cache_purge(tmp_path: Path) -> None:
    originals = tmp_path / "originals"
    cache = tmp_path / "cache"
    adapter = LocalMediaStorage(originals, cache)

    await adapter.put("org/listing/photo.webp", b"RIFFxxxxWEBPsynthetic")
    cached = cache / "org/listing/thumb.webp"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"derived")

    assert (originals / "org/listing/photo.webp").read_bytes().startswith(b"RIFF")
    await adapter.purge_cache(("org/listing/thumb.webp",))
    await adapter.delete("org/listing/photo.webp")
    assert not cached.exists()
    assert not (originals / "org/listing/photo.webp").exists()


async def test_local_storage_rejects_keys_outside_both_roots(tmp_path: Path) -> None:
    adapter = LocalMediaStorage(tmp_path / "originals", tmp_path / "cache")

    with pytest.raises(MediaStorageError):
        await adapter.put("../outside.jpg", b"synthetic")
    with pytest.raises(MediaStorageError):
        await adapter.purge_cache(("../../outside.jpg",))
