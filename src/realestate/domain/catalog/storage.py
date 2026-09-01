"""The small storage port Listing Media depends on (ADR-0038)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MediaStorageError(Exception):
    """A storage or cache operation could not be established."""


@dataclass(frozen=True)
class MediaStorageHealth:
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "status": "ok" if self.ok else "unavailable",
            "detail": self.detail,
        }


class MediaStorage(Protocol):
    """Private original/cache storage, independent of any cloud provider."""

    async def put(self, key: str, content: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def read(self, key: str) -> bytes: ...

    async def purge_cache(self, keys: tuple[str, ...]) -> None: ...

    async def check_health(self) -> MediaStorageHealth: ...
