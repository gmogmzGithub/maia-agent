"""The media-storage port, and the filesystem adapter production runs on."""

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

    async def read(self, key: str) -> bytes: ...

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

    async def read(self, key: str) -> bytes:
        path = self._path(self._root, key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise MediaStorageError("No se pudo leer la fotografía autorizada.") from exc

    async def purge_cache(self, keys: tuple[str, ...]) -> None:
        paths = [self._path(self._cache_root, key) for key in keys]
        await asyncio.to_thread(self._unlink_all, paths)

    @staticmethod
    def _unlink_all(paths: list[Path]) -> None:
        for path in paths:
            path.unlink(missing_ok=True)

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
