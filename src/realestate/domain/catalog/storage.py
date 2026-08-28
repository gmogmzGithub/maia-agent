"""Media-storage port with local production and in-memory test adapters."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Protocol


class MediaStorageError(Exception):
    """A storage or cache operation could not be established."""


class MediaStorage(Protocol):
    async def put(self, key: str, content: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def purge_cache(self, keys: tuple[str, ...]) -> None: ...


class LocalMediaStorage:
    """Filesystem adapter used by local Compose and a future mounted volume."""

    def __init__(self, root: Path, cache_root: Path) -> None:
        self._root = root.resolve()
        self._cache_root = cache_root.resolve()

    async def put(self, key: str, content: bytes) -> None:
        await asyncio.to_thread(self._write, self._path(self._root, key), content)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(self._root, key).unlink, missing_ok=True)

    async def purge_cache(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            await asyncio.to_thread(
                self._path(self._cache_root, key).unlink, missing_ok=True
            )

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _path(root: Path, key: str) -> Path:
        candidate = (root / key).resolve()
        if candidate != root and root not in candidate.parents:
            raise MediaStorageError("La clave de almacenamiento salió de su raíz.")
        return candidate


class InMemoryMediaStorage:
    """Deterministic adapter for behavior and recovery tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.cache_objects: set[str] = set()
        self.fail_delete_once = False
        self.fail_cache_once = False

    async def put(self, key: str, content: bytes) -> None:
        self.objects[key] = bytes(content)

    async def delete(self, key: str) -> None:
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise MediaStorageError("Falla de prueba al borrar el original.")
        self.objects.pop(key, None)

    async def purge_cache(self, keys: tuple[str, ...]) -> None:
        if self.fail_cache_once:
            self.fail_cache_once = False
            raise MediaStorageError("Falla de prueba al purgar cache.")
        self.cache_objects.difference_update(keys)
