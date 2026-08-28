"""In-memory media storage for the catalog suites.

A test double, so it lives with the tests rather than in ``src``: the
failure-injection flags below exist only to make a storage error happen on
demand, and production code should not ship branches whose only job is to raise.
"""

from __future__ import annotations

from realestate.domain.catalog.storage import MediaStorageError


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
