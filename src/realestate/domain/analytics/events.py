"""``AnalyticsEvents.record`` — the only way an event enters measurement.

One entry point, and it writes to the analytics Outbox rather than to the event
store. That separation is the reason a measurement failure cannot damage
anything a customer is waiting for: the caller's transaction records a durable
intent and stops there, and every question about ordering, exclusion, aggregation
and late arrival belongs to :mod:`realestate.domain.analytics.projection`.

Three properties are established here and nowhere else:

* **Idempotency** — the caller supplies the event key. A retried webhook, a
  double-submitted page and a replayed worker tick all produce one row, and the
  repeat is counted rather than discarded silently.
* **Validation** — an event that is not in the taxonomy, or carries an attribute
  nobody declared, is refused. Personal data cannot reach the analytics schema
  because there is no accepted attribute it fits in.
* **Pseudonymisation** — raw session and subject identifiers are replaced before
  the row is written. The raw value exists only in the caller's memory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ANALYTICS_OUTBOX_SEQUENCE,
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
)
from realestate.domain.analytics.definitions import TAXONOMY_VERSION
from realestate.domain.analytics.pseudonyms import Pseudonyms, Purpose
from realestate.domain.analytics.taxonomy import ALLOWED_VALUES, SCHEMAS
from realestate.domain.commercial.actors import Actor, CommercialError

#: The longest attribute string a declared enumerated value can be. Enumerated
#: values are all short; the bound is a second line of defence so a mistake in
#: :data:`ALLOWED_VALUES` cannot open a free-text field.
MAX_VALUE_LENGTH = 40


class EventRejected(CommercialError):
    """The event is not something Product is willing to measure."""

    message = "El evento de medición no es válido."


@dataclass(frozen=True)
class AnalyticsEvent:
    """One thing that happened, described only in measurable terms.

    ``session_value`` and ``subject_value`` are *raw* identifiers — a site
    session cookie, a Contact id — and are pseudonymised before anything is
    stored. They are separate fields from the references so no caller can pass a
    raw value where a reference belongs by getting the argument order wrong.
    """

    event_key: str
    name: AnalyticsEventName
    occurred_at: datetime
    listing_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    session_value: str = ""
    subject_value: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    #: Delivery-side hints the classifier reads. Never stored verbatim.
    bot: bool = False
    internal: bool = False
    synthetic: bool = False


@dataclass(frozen=True)
class Recorded:
    """The outcome of one ``record`` call."""

    event_key: str
    created: bool
    sequence: int


class AnalyticsEvents:
    """Validate, pseudonymise and durably enqueue one domain event."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor
        self._pseudonyms = Pseudonyms(session, actor.organization_id)

    async def record(self, event: AnalyticsEvent) -> Recorded:
        schema = SCHEMAS.get(event.name)
        if schema is None:  # pragma: no cover - enum membership makes this dead
            raise EventRejected("El nombre del evento no está en la taxonomía.")
        key = event.event_key.strip()
        if len(key) < 8:
            raise EventRejected(
                "El evento requiere una clave de idempotencia de al menos 8 caracteres."
            )
        if event.occurred_at.tzinfo is None:
            raise EventRejected("El evento requiere una marca de tiempo con zona.")
        attributes = self._validated(schema.allowed, schema.required, event.attributes)
        if schema.requires_campaign and event.campaign_id is None:
            raise EventRejected("Una exposición pagada requiere su campaña.")
        if schema.requires_listing and event.listing_id is None:
            raise EventRejected("El evento requiere la publicación que describe.")

        existing = await self._session.scalar(
            select(AnalyticsOutboxEntry)
            # Scoped: since Stage 9 the event key is unique *per Organization*,
            # because it is built from product identifiers two Organizations can
            # legitimately share. Unscoped, one brokerage's emission would be
            # counted as a duplicate of another's and silently dropped
            # (ADR-0050).
            .where(AnalyticsOutboxEntry.organization_id == self._actor.organization_id)
            .where(AnalyticsOutboxEntry.event_key == key)
        )
        if existing is not None:
            # Counted, not ignored. A duplicate rate that nobody can see is the
            # difference between "we deduplicate" and "we hope we deduplicate".
            await self._session.execute(
                update(AnalyticsOutboxEntry)
                .where(AnalyticsOutboxEntry.id == existing.id)
                .values(duplicate_attempts=AnalyticsOutboxEntry.duplicate_attempts + 1)
            )
            return Recorded(key, created=False, sequence=existing.sequence)

        payload: dict[str, Any] = {
            "listing_id": str(event.listing_id) if event.listing_id else None,
            "campaign_id": str(event.campaign_id) if event.campaign_id else None,
            "session_reference": await self._pseudonyms.reference(
                Purpose.SESSION, event.session_value
            ),
            "subject_reference": await self._pseudonyms.reference(
                Purpose.SUBJECT, event.subject_value
            ),
            "attributes": attributes,
            "bot": event.bot,
            "internal": event.internal,
            "synthetic": event.synthetic,
        }
        # Read explicitly rather than left to the column default. The caller
        # gets the enqueued position back, and a server-side default on a
        # non-primary-key column would leave the attribute unloaded — a lazy
        # refresh that fails outright inside the async worker.
        sequence = await self._session.scalar(
            select(ANALYTICS_OUTBOX_SEQUENCE.next_value())
        )
        row = AnalyticsOutboxEntry(
            sequence=int(sequence or 0),
            organization_id=self._actor.organization_id,
            event_key=key,
            event_name=event.name.value,
            schema_version=schema.schema_version,
            taxonomy_version=TAXONOMY_VERSION,
            occurred_at=event.occurred_at,
            payload=payload,
            status=AnalyticsOutboxStatus.PENDING.value,
        )
        self._session.add(row)
        await self._session.flush()
        return Recorded(key, created=True, sequence=row.sequence)

    @staticmethod
    def _validated(
        allowed: frozenset[str],
        required: frozenset[str],
        supplied: dict[str, Any],
    ) -> dict[str, Any]:
        """The attributes, or a refusal naming what is wrong with them."""
        unknown = sorted(set(supplied) - allowed)
        if unknown:
            raise EventRejected(
                "El evento contiene atributos no declarados: " + ", ".join(unknown) + "."
            )
        missing = sorted(required - set(supplied))
        if missing:
            raise EventRejected(
                "Al evento le faltan atributos obligatorios: " + ", ".join(missing) + "."
            )
        checked: dict[str, Any] = {}
        for name, value in sorted(supplied.items()):
            permitted = ALLOWED_VALUES.get(name)
            if permitted is not None:
                if not isinstance(value, str) or value not in permitted:
                    raise EventRejected(
                        f"El atributo «{name}» no acepta ese valor."
                    )
                checked[name] = value
                continue
            if isinstance(value, bool):
                checked[name] = value
                continue
            if isinstance(value, (int, float)):
                checked[name] = value
                continue
            raise EventRejected(
                f"El atributo «{name}» sólo acepta números, booleanos o valores "
                "enumerados; no acepta texto libre."
            )
        for name, value in checked.items():
            if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
                raise EventRejected(  # pragma: no cover - enumerations are short
                    f"El atributo «{name}» excede la longitud permitida."
                )
        return checked
