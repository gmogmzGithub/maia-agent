"""The versioned counting rules, and the exact borders they draw.

Every number a report shows depends on a threshold somebody chose: half the card
for one second, five photographs or thirty percent of a gallery. ADR-0044 says a
report has to stay reproducible when those choices change, so the thresholds are
stored per version and read back, never compiled into the query that uses them.

This module is where a border is decided once. ``visible`` and
``significant_exploration`` are the two comparisons the whole funnel rests on,
and having them in one place is what makes "exactly 50 percent counts, 49.99
does not" a fact about the product rather than a coincidence between four
callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import MeasurementDefinition
from realestate.domain.commercial.actors import CommercialError

#: The version Product emits and reads today. Migration 0025 seeds its row.
CURRENT_DEFINITION_VERSION = "measurement-v1"

#: The event taxonomy's own version, carried on every emitted event so a
#: consumer can tell a renamed field from a missing one.
TAXONOMY_VERSION = "analytics-events-v1"


class UnknownDefinition(CommercialError):
    """A report asked for a measurement version Product has never stored."""

    message = "No existe esa versión de definiciones de medición."


@dataclass(frozen=True)
class Attribution:
    """How long an outcome may be reported after an exposure, without cause."""

    view_through_days: int
    engaged_days: int


@dataclass(frozen=True)
class Definition:
    """One frozen set of counting rules."""

    version: str
    effective_from: datetime
    minimum_visible_fraction: float
    minimum_continuous_milliseconds: int
    minimum_photographs: int
    minimum_gallery_fraction: float
    funnel: tuple[str, ...]
    attribution: Attribution
    search_visible_results_per_sponsored: int
    homepage_maximum_sponsored: int
    session_daily_visible_impression_cap: int
    comparable_minimum_sample: int

    def served(self) -> bool:
        """A Served Impression needs nothing beyond having been delivered.

        Spelled as a method rather than left implicit so the distinction from
        :meth:`visible` is visible in the code that reports both. Serving is
        Product's own fact — it put the placement in the response — while
        visibility is a claim about what a person could actually see.
        """
        return True

    def visible(self, *, visible_fraction: float, continuous_milliseconds: int) -> bool:
        """Whether one Served Impression became a Visible Impression.

        Both borders are inclusive. Exactly half the card for exactly one
        second is the rule as written in ADR-0043; a strict comparison would
        quietly under-report every placement that met the published threshold.
        """
        return (
            visible_fraction >= self.minimum_visible_fraction
            and continuous_milliseconds >= self.minimum_continuous_milliseconds
        )

    def significant_exploration(
        self, *, photographs: int, gallery_fraction: float
    ) -> bool:
        """Whether a Gallery open became a Significant Gallery Exploration.

        Either threshold suffices, which matters for a six-photograph Larevia
        gallery: five photographs is 83 percent of it, and requiring both would
        make the milestone unreachable on the smallest tier and trivial on the
        largest.
        """
        return (
            photographs >= self.minimum_photographs
            or gallery_fraction >= self.minimum_gallery_fraction
        )

    def sponsored_slots(self, *, surface: str, visible_results: int) -> int:
        """How many sponsored positions one rendered surface may contain.

        Integer division, not rounding up: "at most one per six visible
        results" means a five-result page sells nothing. Rounding up would let
        a nearly empty page be a majority-sponsored page.
        """
        if surface == "Homepage":
            return self.homepage_maximum_sponsored
        if visible_results <= 0:
            return 0
        return visible_results // self.search_visible_results_per_sponsored


def _attribution(raw: dict[str, Any]) -> Attribution:
    return Attribution(
        view_through_days=int(raw.get("view_through_days", 7)),
        engaged_days=int(raw.get("engaged_days", 90)),
    )


def parse(version: str, effective_from: datetime, raw: dict[str, Any]) -> Definition:
    """Build a :class:`Definition` from one stored row's JSON."""
    visible = dict(raw.get("visible_impression") or {})
    exploration = dict(raw.get("significant_gallery_exploration") or {})
    return Definition(
        version=version,
        effective_from=effective_from,
        minimum_visible_fraction=float(visible.get("minimum_visible_fraction", 0.5)),
        minimum_continuous_milliseconds=int(
            visible.get("minimum_continuous_milliseconds", 1000)
        ),
        minimum_photographs=int(exploration.get("minimum_photographs", 5)),
        minimum_gallery_fraction=float(exploration.get("minimum_gallery_fraction", 0.3)),
        funnel=tuple(str(step) for step in (raw.get("funnel") or ())),
        attribution=_attribution(dict(raw.get("attribution") or {})),
        search_visible_results_per_sponsored=int(
            raw.get("search_visible_results_per_sponsored", 6)
        ),
        homepage_maximum_sponsored=int(raw.get("homepage_maximum_sponsored", 2)),
        session_daily_visible_impression_cap=int(
            raw.get("session_daily_visible_impression_cap", 3)
        ),
        comparable_minimum_sample=int(raw.get("comparable_minimum_sample", 3)),
    )


class MeasurementDefinitions:
    """Read one stored version. The only reader of the definitions table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, version: str | None = None) -> Definition:
        wanted = version or CURRENT_DEFINITION_VERSION
        row = await self._session.scalar(
            select(MeasurementDefinition).where(
                MeasurementDefinition.version == wanted
            )
        )
        if row is None:
            raise UnknownDefinition(
                f"No existe la versión de medición «{wanted}»."
            )
        return parse(row.version, row.effective_from, dict(row.definition))

    async def versions(self) -> tuple[str, ...]:
        rows = await self._session.scalars(
            select(MeasurementDefinition.version).order_by(
                MeasurementDefinition.effective_from
            )
        )
        return tuple(rows)
