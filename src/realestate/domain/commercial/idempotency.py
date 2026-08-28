"""Transactional idempotency for commercial commands without a natural receipt."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import CommercialCommandReceipt
from realestate.domain.commercial.actors import Actor, InvalidTransition


class CommercialCommands:
    """Claim request keys behind one small, durable interface.

    The receipt is inserted in the caller's transaction.  A failed mutation
    rolls it back; a successful retry observes it and performs no second write.
    The payload hash also prevents one key from authorising two different
    commands.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        actor: Actor,
        *,
        command_key: str,
        operation: str,
        subject_type: str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        """Return ``True`` for an exact replay, otherwise claim the key."""
        canonical = json.dumps(
            payload or {}, sort_keys=True, separators=(",", ":"), default=str
        )
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        lock_key = f"{actor.organization_id}:{command_key}"
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(lock_key)))
        )
        receipt = await self._session.scalar(
            select(CommercialCommandReceipt).where(
                CommercialCommandReceipt.organization_id == actor.organization_id,
                CommercialCommandReceipt.command_key == command_key,
            )
        )
        if receipt is not None:
            if (
                receipt.operation != operation
                or receipt.subject_type != subject_type
                or receipt.subject_id != subject_id
                or receipt.payload_hash != payload_hash
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes; "
                    "recarga la página e inténtalo de nuevo."
                )
            return True

        self._session.add(
            CommercialCommandReceipt(
                organization_id=actor.organization_id,
                command_key=command_key,
                operation=operation,
                subject_type=subject_type,
                subject_id=subject_id,
                payload_hash=payload_hash,
                created_by=actor.label,
            )
        )
        await self._session.flush()
        return False
