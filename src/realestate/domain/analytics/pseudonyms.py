"""Turn an identifier into a stable reference nobody can reverse.

Measurement needs to follow one anonymous session through a funnel. It does not
need to know whose session it is, and ADR-0044 says the analytics rows must not
be able to tell anybody. A salted digest gives both: the same input maps to the
same reference every time, and the reference cannot be turned back into the
input without the salt.

The salt lives in the analytics schema rather than in configuration. A
configured secret can be empty, shared between environments, or committed by
accident; a row generated once per Organization and purpose cannot be any of
those. It is created lazily on first use and never rotated automatically —
rotating it would silently break every historic funnel join.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import PseudonymSalt

#: Digest length in hex characters. 32 hex characters is 128 bits of the
#: SHA-256 output: far beyond collision risk at this volume, and short enough
#: that the reference fits an index without being mistaken for a token.
REFERENCE_LENGTH = 32


class Purpose(str, Enum):
    """What a reference is for.

    Separate salts per purpose on purpose: a session reference and a subject
    reference derived from the same salt would let anybody holding both tables
    confirm that one anonymous session belongs to one known Contact.
    """

    SESSION = "session"
    SUBJECT = "subject"


class Pseudonyms:
    """The only place a raw identifier becomes an analytics reference."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self._session = session
        self._organization_id = organization_id
        self._cache: dict[Purpose, str] = {}

    async def reference(self, purpose: Purpose, value: str) -> str:
        """The stable reference for one raw *value*, or a refusal on empty input.

        An empty value returns an empty reference rather than the digest of the
        empty string: a digest would make every unidentified event look like one
        shared session, which is exactly the kind of quiet fabrication a funnel
        must not contain.
        """
        cleaned = value.strip()
        if not cleaned:
            return ""
        salt = await self._salt(purpose)
        digest = hmac.new(
            salt.encode("utf-8"),
            f"{purpose.value}:{cleaned}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest[:REFERENCE_LENGTH]

    async def _salt(self, purpose: Purpose) -> str:
        cached = self._cache.get(purpose)
        if cached is not None:
            return cached
        existing = await self._session.scalar(
            select(PseudonymSalt.salt).where(
                PseudonymSalt.organization_id == self._organization_id,
                PseudonymSalt.purpose == purpose.value,
            )
        )
        if existing is None:
            existing = await self._create(purpose)
        self._cache[purpose] = existing
        return existing

    async def _create(self, purpose: Purpose) -> str:
        """Generate the salt, tolerating a concurrent first writer.

        Two requests can reach the same unsalted purpose at once. The unique
        constraint decides, and the loser re-reads rather than raising: a
        measurement event must not fail because somebody else created the salt
        first.
        """
        candidate = secrets.token_hex(32)
        savepoint = await self._session.begin_nested()
        try:
            self._session.add(
                PseudonymSalt(
                    organization_id=self._organization_id,
                    purpose=purpose.value,
                    salt=candidate,
                )
            )
            await self._session.flush()
        except IntegrityError:
            await savepoint.rollback()
            winner = await self._session.scalar(
                select(PseudonymSalt.salt).where(
                    PseudonymSalt.organization_id == self._organization_id,
                    PseudonymSalt.purpose == purpose.value,
                )
            )
            if winner is None:  # pragma: no cover - the constraint guarantees a row
                raise
            return winner
        await savepoint.commit()
        return candidate
