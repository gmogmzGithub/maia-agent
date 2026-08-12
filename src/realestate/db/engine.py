"""PostgreSQL access for the Deterministic Backend (ADR-0006).

One database holds domain state, the Inbox and Outbox, idempotency records, and
audit history. Checkpoint 0 establishes the engine, the declarative base, and a
liveness probe; business tables arrive with the checkpoint that needs them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every product table."""


@dataclass(frozen=True)
class DatabaseHealth:
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {"status": "ok" if self.ok else "unavailable", "detail": self.detail}


class Database:
    """Owns the engine and session factory for the application's lifetime."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        """One unit of work. The caller commits; an exception rolls back."""
        async with self._sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def check_health(self) -> DatabaseHealth:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return DatabaseHealth(
                ok=False,
                detail=(
                    f"PostgreSQL is not reachable ({exc.__class__.__name__}). "
                    "Start it with `docker compose up -d db`."
                ),
            )
        except Exception as exc:
            # A driver or environment fault (missing greenlet, bad DSN) must be
            # reported through /health rather than crashing application startup.
            return DatabaseHealth(
                ok=False,
                detail=f"PostgreSQL check failed: {exc.__class__.__name__}: {exc}",
            )
        return DatabaseHealth(ok=True, detail="PostgreSQL reachable")

    async def dispose(self) -> None:
        await self._engine.dispose()
