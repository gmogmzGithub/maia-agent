"""Decide whether one event counts, and say why when it does not.

Invalid traffic is not deleted. Every event is stored with the class that was
assigned to it, and the reported numbers filter on ``Valid`` while the excluded
volume is reported next to them. A metric that quietly drops rows and a metric
that never had them look identical to the reader, and only one of them is
honest.

The classifier is deliberately conservative and deliberately dumb. It reads
flags Product itself set at the boundary — this request came from a known
crawler, this call came from an operator surface, this row came from a fixture —
plus one rate check. There is no scoring model and no user-agent string in the
analytics schema: a heuristic nobody can audit would be worse than an
undercount.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AnalyticsDomainEvent, TrafficClass

#: Above this many events from one pseudonymous session inside one minute, the
#: session is treated as implausible rather than as an unusually fast person.
#: A generous ceiling on purpose: excluding real traffic to look tidy is the
#: failure mode that matters here.
IMPLAUSIBLE_EVENTS_PER_MINUTE = 120

#: Case-folded substrings that identify a crawler in the user agent the *site*
#: inspected. The site sends a boolean; the tokens live here so the boundary and
#: the exclusion reason cannot disagree about what "bot" meant.
CRAWLER_TOKENS: tuple[str, ...] = (
    "bot",
    "crawler",
    "spider",
    "slurp",
    "headlesschrome",
    "python-requests",
    "curl/",
    "wget/",
)

EXCLUSION_LABELS: dict[str, str] = {
    TrafficClass.BOT.value: "Robot o rastreador",
    TrafficClass.INTERNAL.value: "Tráfico interno o administrativo",
    TrafficClass.TEST.value: "Datos sintéticos de prueba",
    TrafficClass.IMPLAUSIBLE.value: "Ritmo de eventos no plausible",
}


def looks_like_crawler(user_agent: str) -> bool:
    """Whether a user agent names itself a crawler.

    Used at the HTTP boundary and never stored: the caller turns the answer into
    a boolean and the string stays out of the analytics schema.
    """
    folded = user_agent.casefold()
    return any(token in folded for token in CRAWLER_TOKENS)


@dataclass(frozen=True)
class Classification:
    """One event's traffic class and, when excluded, its readable reason."""

    traffic_class: TrafficClass
    reason: str | None

    @property
    def counts(self) -> bool:
        return self.traffic_class is TrafficClass.VALID


class TrafficClassifier:
    """Assign a traffic class to one enqueued event."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self._session = session
        self._organization_id = organization_id

    async def classify(
        self, payload: dict[str, Any], *, occurred_at: datetime
    ) -> Classification:
        """Bot, then internal, then test, then rate. Order is the precedence.

        Fixed rather than incidental: an internal smoke test run by an operator
        is reported as ``Test`` and not as ``Internal``, so "how much of this
        month was us" and "how much was a fixture" stay separable.
        """
        if bool(payload.get("bot")):
            return Classification(
                TrafficClass.BOT, EXCLUSION_LABELS[TrafficClass.BOT.value]
            )
        if bool(payload.get("synthetic")):
            return Classification(
                TrafficClass.TEST, EXCLUSION_LABELS[TrafficClass.TEST.value]
            )
        if bool(payload.get("internal")):
            return Classification(
                TrafficClass.INTERNAL, EXCLUSION_LABELS[TrafficClass.INTERNAL.value]
            )
        reference = str(payload.get("session_reference") or "")
        if reference and await self._too_fast(reference, occurred_at):
            return Classification(
                TrafficClass.IMPLAUSIBLE,
                EXCLUSION_LABELS[TrafficClass.IMPLAUSIBLE.value],
            )
        return Classification(TrafficClass.VALID, None)

    async def _too_fast(self, reference: str, occurred_at: datetime) -> bool:
        window = timedelta(minutes=1)
        already = await self._session.scalar(
            select(func.count(AnalyticsDomainEvent.id)).where(
                AnalyticsDomainEvent.organization_id == self._organization_id,
                AnalyticsDomainEvent.session_reference == reference,
                AnalyticsDomainEvent.occurred_at >= occurred_at - window,
                AnalyticsDomainEvent.occurred_at <= occurred_at + window,
            )
        )
        return (already or 0) >= IMPLAUSIBLE_EVENTS_PER_MINUTE
