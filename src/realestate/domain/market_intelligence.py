"""Organization-owned sale facts and their Platform analytical projection.

Operational writes always take an :class:`Actor`. Platform analysis never does:
it takes the deliberately narrower :class:`MarketIntelligenceAnalyst`, which has
no method for reaching Contacts, conversations, documents or Organization CRM.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    MarketContribution,
    MarketRecordRevision,
    MarketSaleRecord,
    MarketSaleResolution,
    MarketSaleResolutionMember,
    Property,
    PurchaseProfile,
    SharedBuyerProfile,
    SharedMarketRecord,
    SharedMarketRecordVersion,
    TransactionJourney,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    MissingEvidence,
    NotAuthorized,
    NotFound,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


FIELD_STATES = frozenset({"NotCaptured", "NotProvided", "Provided"})
PROFILE_FIELDS = frozenset(
    {
        "birth_year",
        "monthly_income",
        "income_currency",
        "adults",
        "children",
        "financial_dependants",
        "co_buyers",
        "home_purchase_number",
        "payment_path",
        "financing_modality",
        "down_payment",
        "down_payment_currency",
        "target_monthly_payment",
        "target_payment_currency",
        "preapproval_state",
    }
)
SALE_FIELDS = frozenset(
    {
        "property_uuid",
        "property_type",
        "municipality",
        "colonia",
        "address",
        "land_area_sqm",
        "construction_area_sqm",
        "bedrooms",
        "bathrooms",
        "parking_spaces",
        "construction_year",
        "property_condition",
        "publication_date",
        "completion_date",
        "published_price",
        "published_currency",
        "appraisal_value",
        "appraisal_currency",
        "paid_price",
        "paid_currency",
    }
)


@dataclass(frozen=True)
class MarketIntelligenceAnalyst:
    """The dedicated analytical authority; deliberately not an Actor."""

    label: str


@dataclass(frozen=True)
class ProjectionReport:
    projected: int = 0
    failed: int = 0


@dataclass(frozen=True)
class ComparableFilters:
    property_type: str | None = None
    municipality: str | None = None
    currency: str | None = None
    exclude_record_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ComparableReport:
    sample_size: int
    records: tuple[SharedMarketRecord, ...]
    aggregate_available: bool
    median_paid_price: Decimal | None
    minimum_paid_price: Decimal | None
    maximum_paid_price: Decimal | None
    aggregate_currency: str | None


@dataclass(frozen=True)
class MarketAggregateSummary:
    total_paid_price: Decimal | None
    median_paid_price_per_sqm: Decimal | None
    median_published_to_paid_difference: Decimal | None
    median_days_to_completion: Decimal | None
    distributions: dict[str, dict[str, int]]


def _validate_states(states: dict[str, str], allowed: frozenset[str]) -> None:
    unknown = set(states) - allowed
    if unknown:
        raise InvalidTransition(
            "Campos desconocidos: " + ", ".join(sorted(unknown)) + "."
        )
    invalid = {value for value in states.values() if value not in FIELD_STATES}
    if invalid:
        raise InvalidTransition(
            "El estado de un dato debe ser NotCaptured, NotProvided o Provided."
        )


class MarketRecords:
    """Current Profile and sale facts inside one Organization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _journey_for_opportunity(
        self, actor: Actor, opportunity_id: uuid.UUID, *, lock: bool = False
    ) -> TransactionJourney:
        statement = select(TransactionJourney).where(
            TransactionJourney.organization_id == actor.organization_id,
            TransactionJourney.opportunity_id == opportunity_id,
        )
        if lock:
            statement = statement.with_for_update()
        journey = await self._session.scalar(statement)
        if journey is None:
            raise MissingEvidence(
                "Inicia el trámite de compra antes de registrar datos de venta."
            )
        actor.require_owns(
            journey.responsible_advisor_id,
            "No encontramos ese trámite dentro de tu trabajo asignado.",
        )
        return journey

    async def profile(self, actor: Actor, opportunity_id: uuid.UUID) -> PurchaseProfile:
        journey = await self._journey_for_opportunity(actor, opportunity_id)
        row = await self._session.scalar(
            select(PurchaseProfile).where(
                PurchaseProfile.organization_id == actor.organization_id,
                PurchaseProfile.journey_id == journey.id,
            )
        )
        if row is None:
            raise NotFound()
        return row

    async def sale(
        self, actor: Actor, opportunity_id: uuid.UUID, *, lock: bool = False
    ) -> MarketSaleRecord:
        journey = await self._journey_for_opportunity(actor, opportunity_id, lock=lock)
        statement = select(MarketSaleRecord).where(
            MarketSaleRecord.organization_id == actor.organization_id,
            MarketSaleRecord.journey_id == journey.id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFound()
        return row

    async def update_profile(
        self,
        actor: Actor,
        opportunity_id: uuid.UUID,
        *,
        values: dict[str, Any],
        field_states: dict[str, str],
    ) -> PurchaseProfile:
        actor.require_writable()
        if actor.is_product:
            raise NotAuthorized(
                "Maia puede pedir el dato, pero no inventarlo ni registrarlo."
            )
        _validate_states(field_states, PROFILE_FIELDS)
        unknown = set(values) - PROFILE_FIELDS
        if unknown:
            raise InvalidTransition(
                "Campos desconocidos: " + ", ".join(sorted(unknown)) + "."
            )
        row = await self.profile(actor, opportunity_id)
        sale = await self.sale(actor, opportunity_id)
        if sale.state == "Completed":
            raise InvalidTransition(
                "Una venta completada sólo puede corregirse directamente en PostgreSQL."
            )
        for name, value in values.items():
            setattr(row, name, value)
        states = dict(row.field_states)
        states.update(field_states)
        for name, value in values.items():
            states[name] = (
                "Provided" if value is not None else states.get(name, "NotCaptured")
            )
        row.field_states = states
        row.updated_at = _now()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="UpdatePurchaseProfile",
            subject_type="PurchaseProfile",
            subject_id=str(row.id),
            details={"fields": sorted(set(values) | set(field_states))},
            commit=False,
        )
        await self._session.flush()
        return row

    async def update_sale(
        self,
        actor: Actor,
        opportunity_id: uuid.UUID,
        *,
        values: dict[str, Any],
        field_states: dict[str, str],
    ) -> MarketSaleRecord:
        actor.require_writable()
        if actor.is_product:
            raise NotAuthorized("Maia no puede confirmar datos de una venta.")
        _validate_states(field_states, SALE_FIELDS)
        unknown = set(values) - SALE_FIELDS
        if unknown:
            raise InvalidTransition(
                "Campos desconocidos: " + ", ".join(sorted(unknown)) + "."
            )
        row = await self.sale(actor, opportunity_id, lock=True)
        if row.state == "Completed":
            raise InvalidTransition(
                "Una venta completada sólo puede corregirse directamente en PostgreSQL."
            )
        if row.state == "Cancelled":
            raise InvalidTransition(
                "El trámite cancelado ya no acepta cambios operativos."
            )
        for name, value in values.items():
            setattr(row, name, value)
        property_id = values.get("property_uuid")
        if property_id is not None:
            property_row = await self._session.scalar(
                select(Property).where(
                    Property.organization_id == actor.organization_id,
                    Property.id == property_id,
                )
            )
            if property_row is None:
                raise NotFound("No encontramos esa propiedad en tu organización.")
            # Reuse authoritative catalog truth. The Advisor only supplies facts
            # the catalog does not know, so the workspace never asks twice.
            catalog_facts = property_row.physical_facts
            defaults: dict[str, Any] = {
                "property_type": property_row.property_type,
                "address": property_row.visit_address,
                "municipality": catalog_facts.get("municipality"),
                "colonia": catalog_facts.get("colonia"),
                "land_area_sqm": catalog_facts.get("land_area_sqm"),
                "construction_area_sqm": catalog_facts.get("construction_area_sqm"),
                "bedrooms": catalog_facts.get("bedrooms"),
                "bathrooms": catalog_facts.get("bathrooms"),
                "parking_spaces": catalog_facts.get("parking_spaces"),
                "construction_year": catalog_facts.get("construction_year"),
            }
            for name, value in defaults.items():
                if name not in values and value is not None:
                    setattr(row, name, value)
        states = dict(row.field_states)
        states.update(field_states)
        for name, value in values.items():
            states[name] = (
                "Provided" if value is not None else states.get(name, "NotCaptured")
            )
        row.field_states = states
        row.updated_at = _now()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="UpdateMarketSaleRecord",
            subject_type="MarketSaleRecord",
            subject_id=str(row.id),
            details={"fields": sorted(set(values) | set(field_states))},
            commit=False,
        )
        await self._session.flush()
        return row

    async def complete_for_won(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> MarketSaleRecord:
        """Enforce ADR-0058 immediately before Opportunity Won is written."""
        actor.require_administrator()
        actor.require_writable()
        if actor.member_id is None:
            raise NotAuthorized()
        row = await self.sale(actor, opportunity_id, lock=True)
        missing: list[str] = []
        for field, label in (
            ("property_uuid", "Propiedad"),
            ("property_type", "tipo de propiedad"),
            ("municipality", "municipio"),
            ("completion_date", "fecha de cierre"),
            ("paid_price", "precio pagado"),
            ("paid_currency", "moneda"),
        ):
            if getattr(row, field) is None:
                missing.append(label)
        if missing:
            raise MissingEvidence(
                "No se puede marcar Ganada. Faltan datos mínimos de venta: "
                + ", ".join(missing)
                + "."
            )
        moment = _now()
        row.state = "Completed"
        row.outcome = "Won"
        row.completed_by = actor.member_id
        row.completed_at = moment
        row.updated_at = moment
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="CompleteMarketSaleRecord",
            subject_type="MarketSaleRecord",
            subject_id=str(row.id),
            details={"opportunity_id": str(opportunity_id)},
            commit=False,
        )
        await self._session.flush()
        return row

    async def revisions(
        self, actor: Actor, source_id: uuid.UUID
    ) -> tuple[MarketRecordRevision, ...]:
        rows = await self._session.scalars(
            select(MarketRecordRevision)
            .where(
                MarketRecordRevision.organization_id == actor.organization_id,
                MarketRecordRevision.source_id == source_id,
            )
            .order_by(MarketRecordRevision.source_version.desc())
        )
        return tuple(rows)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _integer(value: Any) -> int | None:
    return None if value is None else int(value)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _age_band(age: int) -> str:
    if age < 30:
        return "<30"
    if age < 40:
        return "30–39"
    if age < 50:
        return "40–49"
    if age < 60:
        return "50–59"
    return "60+"


def _income_band(income: Decimal) -> str:
    if income < 25_000:
        return "<25k"
    if income < 50_000:
        return "25k–49,999"
    if income < 100_000:
        return "50k–99,999"
    return "100k+"


def _date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (Decimal, date, datetime, uuid.UUID)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class MarketProjector:
    """Idempotently replace current central facts from the durable outbox."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def drain(self, *, limit: int = 100) -> ProjectionReport:
        contributions = list(
            await self._session.scalars(
                select(MarketContribution)
                .where(MarketContribution.state.in_(["Pending", "Failed"]))
                .order_by(MarketContribution.created_at, MarketContribution.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        projected = 0
        failed = 0
        for contribution in contributions:
            contribution.attempts += 1
            try:
                if contribution.source_type == "MarketSaleRecord":
                    await self._project_sale(contribution)
                else:
                    await self._project_profile(contribution)
            except Exception as exc:  # one malformed row must not block the queue
                contribution.state = "Failed"
                contribution.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                failed += 1
            else:
                contribution.state = "Projected"
                contribution.projected_at = _now()
                contribution.last_error = None
                projected += 1
        await self._session.flush()
        return ProjectionReport(projected=projected, failed=failed)

    async def _project_sale(self, contribution: MarketContribution) -> None:
        payload = contribution.payload
        existing = await self._session.scalar(
            select(SharedMarketRecord)
            .where(
                SharedMarketRecord.source_organization_id
                == contribution.organization_id,
                SharedMarketRecord.source_record_id == contribution.source_id,
            )
            .with_for_update()
        )
        if (
            existing is not None
            and existing.source_version >= contribution.source_version
        ):
            return
        if existing is not None:
            self._session.add(
                SharedMarketRecordVersion(
                    source_record_id=existing.source_record_id,
                    source_version=existing.source_version,
                    values=_json_safe(
                        {
                            column.name: getattr(existing, column.name)
                            for column in SharedMarketRecord.__table__.columns
                            if column.name not in {"id", "projected_at"}
                        }
                    ),
                )
            )
            row = existing
        else:
            row = SharedMarketRecord(
                source_organization_id=contribution.organization_id,
                source_record_id=contribution.source_id,
                source_version=contribution.source_version,
                state="Preparation",
                outcome="InProgress",
                field_states={},
            )
            self._session.add(row)
        row.source_version = contribution.source_version
        for name in (
            "state",
            "outcome",
            "property_type",
            "municipality",
            "colonia",
            "bedrooms",
            "parking_spaces",
            "construction_year",
            "property_condition",
            "published_currency",
            "appraisal_currency",
            "paid_currency",
            "field_states",
        ):
            setattr(row, name, payload.get(name))
        row.property_uuid = _uuid(payload.get("property_uuid"))
        for name in (
            "land_area_sqm",
            "construction_area_sqm",
            "bathrooms",
            "published_price",
            "appraisal_value",
            "paid_price",
        ):
            setattr(row, name, _decimal(payload.get(name)))
        row.publication_date = _date(payload.get("publication_date"))
        row.completion_date = _date(payload.get("completion_date"))
        row.projected_at = _now()

    async def _project_profile(self, contribution: MarketContribution) -> None:
        payload = contribution.payload
        sale_id = await self._session.scalar(
            select(MarketSaleRecord.id).where(
                MarketSaleRecord.organization_id == contribution.organization_id,
                MarketSaleRecord.purchase_profile_id == contribution.source_id,
            )
        )
        if sale_id is None:
            raise RuntimeError("Purchase Profile has no Market Sale Record")
        existing = await self._session.scalar(
            select(SharedBuyerProfile)
            .where(
                SharedBuyerProfile.source_organization_id
                == contribution.organization_id,
                SharedBuyerProfile.source_profile_id == contribution.source_id,
            )
            .with_for_update()
        )
        facts = {name: payload.get(name) for name in sorted(PROFILE_FIELDS)}
        if existing is None:
            existing = SharedBuyerProfile(
                source_organization_id=contribution.organization_id,
                source_profile_id=contribution.source_id,
                source_version=contribution.source_version,
                source_sale_record_id=sale_id,
                facts=facts,
                field_states=payload.get("field_states") or {},
            )
            self._session.add(existing)
        elif existing.source_version < contribution.source_version:
            existing.source_version = contribution.source_version
            existing.source_sale_record_id = sale_id
            existing.facts = facts
            existing.field_states = payload.get("field_states") or {}
            existing.projected_at = _now()


class SharedMarketDataset:
    """Analyst-only reads, duplicate decisions and privacy-bounded reports."""

    MINIMUM_AGGREGATE_SAMPLE = 5

    def __init__(
        self, session: AsyncSession, analyst: MarketIntelligenceAnalyst
    ) -> None:
        self._session = session
        self._analyst = analyst

    async def duplicate_candidates(
        self,
    ) -> tuple[tuple[SharedMarketRecord, SharedMarketRecord], ...]:
        records = list(
            await self._session.scalars(
                select(SharedMarketRecord)
                .where(
                    SharedMarketRecord.state == "Completed",
                    SharedMarketRecord.property_uuid.is_not(None),
                    SharedMarketRecord.completion_date.is_not(None),
                    SharedMarketRecord.paid_price.is_not(None),
                )
                .order_by(SharedMarketRecord.completion_date, SharedMarketRecord.id)
            )
        )
        matches: list[tuple[SharedMarketRecord, SharedMarketRecord]] = []
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                if left.source_organization_id == right.source_organization_id:
                    continue
                if (
                    left.resolution_id is not None
                    and left.resolution_id == right.resolution_id
                ):
                    continue
                if (
                    left.property_uuid == right.property_uuid
                    and left.completion_date == right.completion_date
                    and left.paid_price == right.paid_price
                    and left.paid_currency == right.paid_currency
                ):
                    matches.append((left, right))
        return tuple(matches)

    async def completed_record(self, record_id: uuid.UUID) -> SharedMarketRecord | None:
        found: SharedMarketRecord | None = await self._session.scalar(
            select(SharedMarketRecord).where(
                SharedMarketRecord.id == record_id,
                SharedMarketRecord.state == "Completed",
            )
        )
        return found

    async def resolve_duplicate(
        self, record_ids: tuple[uuid.UUID, ...], *, reason: str
    ) -> MarketSaleResolution:
        unique_ids = tuple(dict.fromkeys(record_ids))
        if len(unique_ids) < 2:
            raise MissingEvidence("Selecciona al menos dos contribuciones.")
        clean_reason = reason.strip()
        if not clean_reason:
            raise MissingEvidence("Explica por qué describen la misma venta.")
        rows = list(
            await self._session.scalars(
                select(SharedMarketRecord)
                .where(SharedMarketRecord.id.in_(unique_ids))
                .with_for_update()
            )
        )
        if len(rows) != len(unique_ids):
            raise NotFound()
        if any(row.state != "Completed" for row in rows):
            raise InvalidTransition("Sólo ventas completadas pueden resolverse juntas.")
        if any(row.resolution_id is not None for row in rows):
            raise InvalidTransition("Una contribución ya pertenece a otra resolución.")
        resolution = MarketSaleResolution(
            reason=clean_reason,
            resolved_by=self._analyst.label,
        )
        self._session.add(resolution)
        await self._session.flush()
        for row in rows:
            row.resolution_id = resolution.id
            self._session.add(
                MarketSaleResolutionMember(
                    resolution_id=resolution.id,
                    shared_record_id=row.id,
                )
            )
        await self._session.flush()
        return resolution

    async def comparables(self, filters: ComparableFilters) -> ComparableReport:
        statement = select(SharedMarketRecord).where(
            SharedMarketRecord.state == "Completed",
            SharedMarketRecord.outcome == "Won",
            SharedMarketRecord.paid_price.is_not(None),
            SharedMarketRecord.paid_currency.is_not(None),
        )
        if filters.property_type:
            statement = statement.where(
                SharedMarketRecord.property_type == filters.property_type
            )
        if filters.municipality:
            statement = statement.where(
                SharedMarketRecord.municipality == filters.municipality
            )
        if filters.currency:
            statement = statement.where(
                SharedMarketRecord.paid_currency == filters.currency
            )
        if filters.exclude_record_id:
            statement = statement.where(
                SharedMarketRecord.id != filters.exclude_record_id
            )
        rows = list(
            await self._session.scalars(
                statement.order_by(
                    SharedMarketRecord.completion_date.desc(),
                    SharedMarketRecord.id,
                )
            )
        )
        # One representative per human-resolved sale; unresolved contributions
        # remain separate because automatic merging is explicitly forbidden.
        unique: dict[uuid.UUID, SharedMarketRecord] = {}
        for row in rows:
            unique.setdefault(row.resolution_id or row.id, row)
        records = tuple(unique.values())
        prices = sorted(row.paid_price for row in records if row.paid_price is not None)
        sample = len(prices)
        currencies = {row.paid_currency for row in records if row.paid_currency}
        aggregate = sample >= self.MINIMUM_AGGREGATE_SAMPLE and len(currencies) == 1
        median: Decimal | None = None
        if aggregate:
            midpoint = sample // 2
            median = (
                prices[midpoint]
                if sample % 2
                else (prices[midpoint - 1] + prices[midpoint]) / Decimal("2")
            )
        return ComparableReport(
            sample_size=sample,
            records=records,
            aggregate_available=aggregate,
            median_paid_price=median,
            minimum_paid_price=prices[0] if aggregate else None,
            maximum_paid_price=prices[-1] if aggregate else None,
            aggregate_currency=next(iter(currencies)) if aggregate else None,
        )

    async def aggregate_summary(
        self, report: ComparableReport
    ) -> MarketAggregateSummary:
        """Derive the v1 internal dashboard without exposing buyer rows."""
        if not report.aggregate_available:
            return MarketAggregateSummary(None, None, None, None, {})
        records = report.records
        profiles = list(
            await self._session.scalars(
                select(SharedBuyerProfile).where(
                    SharedBuyerProfile.source_sale_record_id.in_(
                        row.source_record_id for row in records
                    )
                )
            )
        )
        profile_by_sale = {row.source_sale_record_id: row.facts for row in profiles}
        per_sqm = [
            row.paid_price / row.construction_area_sqm
            for row in records
            if row.paid_price is not None
            and row.construction_area_sqm is not None
            and row.construction_area_sqm > 0
        ]
        differences = [
            row.published_price - row.paid_price
            for row in records
            if row.published_price is not None and row.paid_price is not None
        ]
        days = [
            Decimal((row.completion_date - row.publication_date).days)
            for row in records
            if row.completion_date is not None and row.publication_date is not None
        ]
        distributions: dict[str, Counter[str]] = {
            "property_type": Counter(),
            "municipality": Counter(),
            "payment_path": Counter(),
            "home_purchase_number": Counter(),
            "buyer_age": Counter(),
            "monthly_income": Counter(),
            "children": Counter(),
            "financial_dependants": Counter(),
        }
        for row in records:
            if row.property_type:
                distributions["property_type"][row.property_type] += 1
            if row.municipality:
                distributions["municipality"][row.municipality] += 1
            facts = profile_by_sale.get(row.source_record_id, {})
            payment_path = facts.get("payment_path")
            if payment_path:
                distributions["payment_path"][str(payment_path)] += 1
            purchase_number = _integer(facts.get("home_purchase_number"))
            if purchase_number is not None:
                label = str(purchase_number) if purchase_number < 3 else "3+"
                distributions["home_purchase_number"][label] += 1
            birth_year = _integer(facts.get("birth_year"))
            if birth_year is not None and row.completion_date is not None:
                age = row.completion_date.year - birth_year
                distributions["buyer_age"][_age_band(age)] += 1
            income = _decimal(facts.get("monthly_income"))
            if income is not None:
                currency = str(facts.get("income_currency") or "sin moneda")
                distributions["monthly_income"][
                    f"{currency} {_income_band(income)}"
                ] += 1
            for field in ("children", "financial_dependants"):
                count = _integer(facts.get(field))
                if count is not None:
                    distributions[field][str(count) if count < 3 else "3+"] += 1
        return MarketAggregateSummary(
            total_paid_price=sum(
                (row.paid_price for row in records if row.paid_price is not None),
                Decimal("0"),
            ),
            median_paid_price_per_sqm=_median(per_sqm),
            median_published_to_paid_difference=_median(differences),
            median_days_to_completion=_median(days),
            distributions={
                name: dict(sorted(counts.items()))
                for name, counts in distributions.items()
                if counts
            },
        )

    async def completeness(self) -> dict[str, int]:
        total = int(
            await self._session.scalar(
                select(func.count(SharedMarketRecord.id)).where(
                    SharedMarketRecord.state == "Completed"
                )
            )
            or 0
        )
        complete_comparison = int(
            await self._session.scalar(
                select(func.count(SharedMarketRecord.id)).where(
                    SharedMarketRecord.state == "Completed",
                    SharedMarketRecord.construction_area_sqm.is_not(None),
                    SharedMarketRecord.published_price.is_not(None),
                    SharedMarketRecord.appraisal_value.is_not(None),
                )
            )
            or 0
        )
        return {"completed": total, "comparison_complete": complete_comparison}
