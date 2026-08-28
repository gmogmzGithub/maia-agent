"""External inventory behavior through its stable Product interfaces."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from realestate.db.engine import Database
from realestate.db.models import (
    ExternalCandidateState,
    ExternalInventoryScope,
    ExternalListingCandidate,
    InventorySourceStatus,
)
from realestate.domain.external_inventory.health import InventorySourceHealth
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.ports import InventorySourceError, SourceNotFound
from realestate.domain.external_inventory.revalidation import ListingRevalidation
from realestate.domain.external_inventory.search import AuthorizedInventorySearch
from realestate.domain.external_inventory.types import (
    InventorySearchCriteria,
    IntendedAction,
    SourcePage,
)
from realestate.worker.external_inventory import ExternalInventoryCleanupWorker
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures.commercial import ADMIN_LOGIN, actor_for, provision, reset
from tests.fixtures.external_inventory import FakeInventorySource, easybroker_property
from tests.fixtures.public_site import publish_listing

pytestmark = requires_postgres
NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        for table_name in (
            "listing_revalidations",
            "external_offer_candidates",
            "external_listing_candidates",
            "inventory_source_health",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        await reset(session)
        for table_name in (
            "listing_media",
            "listing_offers",
            "catalog_listings",
            "properties",
            "unit_models",
            "developments",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        await reset(session, members=True)
        await provision(session)
    yield database
    await database.dispose()


async def test_pagination_partial_results_and_health_are_durable(database: Database) -> None:
    first = easybroker_property("EB-PAGE-1")
    second = easybroker_property("EB-PAGE-2", municipality="Guadalajara")
    source = FakeInventorySource([first, second])
    source.pages = {
        None: SourcePage(records=({"public_id": "EB-PAGE-1"},), next_cursor="2"),
        "2": SourcePage(records=({"public_id": "EB-PAGE-2"},), next_cursor="3"),
    }
    source.list_errors["3"] = InventorySourceError("timeout", "provider timed out")

    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        result = await ExternalInventory(session, actor, source).synchronize(at=NOW)
        health = await InventorySourceHealth(
            session,
            actor,
            credential_configured=True,
            mls_access_confirmed=True,
            retention_permission_confirmed=True,
        ).read("EasyBroker")
        count = await session.scalar(select(func.count()).select_from(ExternalListingCandidate))

    assert result.status == InventorySourceStatus.PARTIAL.value
    assert result.fetched == result.accepted == 2
    assert result.error_code == "timeout"
    assert count == 2
    assert health.last_error_code == "timeout"
    assert [call[1] for call in source.list_calls] == [None, "2", "3"]


async def test_unconfirmed_retention_permission_blocks_caching_before_network(
    database: Database,
) -> None:
    source = FakeInventorySource()
    source.retention_permission_confirmed = False
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        result = await ExternalInventory(session, actor, source).synchronize(at=NOW)
        health = await InventorySourceHealth(session, actor).read("EasyBroker")
        count = await session.scalar(
            select(func.count()).select_from(ExternalListingCandidate)
        )

    assert result.status == InventorySourceStatus.DISABLED.value
    assert result.error_code == "retention_not_confirmed"
    assert health.retention_permission_confirmed is False
    assert count == 0
    assert source.list_calls == []

    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(InventorySourceError) as raised:
            await ExternalInventory(session, actor, source).refresh_for_use(
                "EB-FAKE-001", at=NOW
            )
    assert raised.value.code == "retention_not_confirmed"


async def test_sync_detects_cursor_loops_missing_ids_and_page_safety_limit(
    database: Database,
) -> None:
    source = FakeInventorySource()
    source.pages = {
        None: SourcePage(records=({},), next_cursor="2"),
        "2": SourcePage(records=({"public_id": "EB-FAKE-001"},), next_cursor="2"),
    }
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        looped = await ExternalInventory(session, actor, source).synchronize(at=NOW)

    assert looped.status == InventorySourceStatus.PARTIAL.value
    assert looped.error_code == "cursor_loop"
    assert looped.fetched == 2
    assert looped.rejected == 1

    source.pages = {
        None: SourcePage(
            records=({"public_id": "EB-FAKE-001"},), next_cursor="2"
        )
    }
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        bounded = await ExternalInventory(session, actor, source).synchronize(
            at=NOW + timedelta(minutes=1), max_pages=1
        )
    assert bounded.error_code == "page_limit"
    assert bounded.status == InventorySourceStatus.PARTIAL.value


async def test_rate_limit_and_unmappable_detail_are_reported_without_crashing(
    database: Database,
) -> None:
    source = FakeInventorySource()
    source.list_errors[None] = InventorySourceError(
        "rate_limited", "slow down", retry_after_seconds=10
    )
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        limited = await ExternalInventory(session, actor, source).synchronize(at=NOW)
        health = await InventorySourceHealth(session, actor).read("EasyBroker")
    assert limited.status == InventorySourceStatus.RATE_LIMITED.value
    assert health.rate_limited_until == NOW + timedelta(seconds=10)

    source = FakeInventorySource()
    source.retrieve_errors["EB-FAKE-001"] = InventorySourceError(
        "timeout", "detail timed out"
    )
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        invalid = await ExternalInventory(session, actor, source).synchronize(
            at=NOW + timedelta(minutes=1)
        )
    assert invalid.status == InventorySourceStatus.PARTIAL.value
    assert invalid.rejected == 1
    assert invalid.error_code == "partial_records"


async def test_same_looking_source_records_are_never_auto_merged(database: Database) -> None:
    first = easybroker_property("EB-DUP-1")
    second = copy.deepcopy(first)
    second["public_id"] = "EB-DUP-2"
    source = FakeInventorySource([first, second])

    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        result = await ExternalInventory(session, actor, source).synchronize(at=NOW)
        identities = tuple(
            await session.scalars(
                select(ExternalListingCandidate.source_listing_id).order_by(
                    ExternalListingCandidate.source_listing_id
                )
            )
        )

    assert result.accepted == 2
    assert identities == ("EB-DUP-1", "EB-DUP-2")


async def test_provider_failure_cannot_degrade_matching_organization_inventory(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        own = await publish_listing(session, actor, "own-stage-six")
        search = AuthorizedInventorySearch(session, actor, FailingExternal())  # type: ignore[arg-type]

        results = await search.search(
            InventorySearchCriteria(municipality="Zapopan"), at=NOW
        )

    assert [row.listing_id for row in results] == [own.listing_id]
    assert results[0].source_kind == "Organization"
    assert not results[0].requires_use_time_revalidation


async def test_strict_service_area_rejects_outside_and_ambiguous_locations(
    database: Database,
) -> None:
    outside = easybroker_property("EB-OUT", municipality="Tlajomulco de Zúñiga")
    ambiguous = easybroker_property(
        "EB-METRO", municipality="Zona Metropolitana de Guadalajara"
    )
    source = FakeInventorySource([outside, ambiguous])

    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        result = await ExternalInventory(session, actor, source).synchronize(at=NOW)
        rows = list(await session.scalars(select(ExternalListingCandidate)))

    assert result.accepted == 0
    assert result.rejected == 2
    assert {row.authority_state for row in rows} == {ExternalCandidateState.DENIED.value}
    with pytest.raises(ValueError, match="Guadalajara, Zapopan o Tlaquepaque"):
        InventorySearchCriteria(municipality="Tlajomulco")


async def test_authorized_candidate_search_and_successful_use_time_revalidation(
    database: Database,
) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        assert candidate.authority_state == "Pending"
        await inventory.confirm_evidence(
            candidate.listing_id,
            authority_evidence="Colaboración sintética certificada para prueba",
            attribution="Inmobiliaria Demo · Agente Demo",
            collaboration_authorized=True,
            commission={"type": "percentage", "value": "2.5"},
            availability="Available",
            at=NOW,
        )

        results = await inventory.search(
            InventorySearchCriteria(municipality="Zapopan", at=NOW + timedelta(minutes=1))
        )
        decision = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id, IntendedAction.RECOMMEND, NOW + timedelta(minutes=2)
        )

    assert len(results) == 1
    assert results[0].source_listing_id == "EB-FAKE-001"
    assert results[0].match_quality.value == "Exact"
    assert decision.outcome == "Eligible"
    assert decision.reasons == ()


@pytest.mark.parametrize("action", list(IntendedAction))
async def test_each_customer_use_requires_the_same_revalidation_gate(
    database: Database, action: IntendedAction
) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        decision = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id, action, NOW + timedelta(minutes=1)
        )

    assert decision.outcome == "Pending"
    assert "la autoridad de uso no está confirmada" in decision.reasons


async def test_price_change_and_revoked_collaboration_fail_closed(database: Database) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        await inventory.confirm_evidence(
            candidate.listing_id,
            authority_evidence="Evidencia sintética",
            attribution="Fuente demo",
            collaboration_authorized=True,
            commission={"value": "2.5%"},
            availability="Available",
            at=NOW,
        )
        source.details["EB-FAKE-001"]["operations"][0]["amount"] = 6_000_000
        changed = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id,
            IntendedAction.RECOMMEND,
            NOW + timedelta(minutes=1),
        )
        source.details["EB-FAKE-001"]["collaboration_authorized"] = False
        revoked = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id,
            IntendedAction.APPOINTMENT,
            NOW + timedelta(minutes=2),
        )

    assert changed.outcome == "Pending"
    assert any("cambió el precio" in reason for reason in changed.reasons)
    assert revoked.outcome == "Denied"
    assert any("revocada" in reason for reason in revoked.reasons)


async def test_stale_or_unreachable_source_never_reuses_old_approval(database: Database) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        source.retrieve_errors["EB-FAKE-001"] = InventorySourceError(
            "timeout", "provider timeout"
        )
        decision = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id,
            IntendedAction.SHARE,
            NOW + timedelta(hours=1),
        )

    assert decision.outcome == "Pending"
    assert any("timeout" in reason for reason in decision.reasons)
    assert any("vencida" in reason for reason in decision.reasons)


async def test_withdrawal_invalidates_immediately_and_cache_is_deleted_by_24_hours(
    database: Database,
) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        source.retrieve_errors["EB-FAKE-001"] = SourceNotFound()
        decision = await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id,
            IntendedAction.RECOMMEND,
            NOW + timedelta(minutes=1),
        )
        before_due = await inventory.purge_due(at=NOW + timedelta(hours=23))
        on_due = await inventory.purge_due(at=NOW + timedelta(hours=25))
        row = await session.get(ExternalListingCandidate, candidate.listing_id)

    assert decision.outcome == "Denied"
    assert before_due == 0
    assert on_due == 1
    assert row is not None
    assert row.raw_payload == {}
    assert row.cache_deleted_at is not None


async def test_cleanup_worker_deletes_due_cache_and_paces_itself(
    database: Database,
) -> None:
    source = FakeInventorySource()
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        source.retrieve_errors["EB-FAKE-001"] = SourceNotFound()
        await ListingRevalidation(session, actor, inventory).evaluate(
            candidate.listing_id,
            IntendedAction.RECOMMEND,
            NOW + timedelta(minutes=1),
        )

    worker = ExternalInventoryCleanupWorker(database, source)
    deleted = await worker.tick(now=NOW + timedelta(hours=24))
    skipped = await worker.tick(now=NOW + timedelta(hours=24, minutes=1))
    async with database.session_scope() as session:
        row = await session.get(ExternalListingCandidate, candidate.listing_id)

    assert deleted == 1
    assert skipped is None
    assert row is not None
    assert row.cache_deleted_at == NOW + timedelta(hours=24)


async def test_refresh_and_recommendation_are_serialized_by_candidate_lock(
    database: Database,
) -> None:
    source = BlockingSource()
    async with database.session_scope() as setup:
        actor = await actor_for(setup, ADMIN_LOGIN)
        inventory = ExternalInventory(setup, actor, source)
        await inventory.synchronize(at=NOW)
        candidate = (await inventory.list_for_administration())[0]
        await inventory.confirm_evidence(
            candidate.listing_id,
            authority_evidence="Evidencia sintética",
            attribution="Fuente demo",
            collaboration_authorized=True,
            commission={"value": "2.5%"},
            availability="Available",
            at=NOW,
        )
    source.block_next = True

    async def recommend() -> str:
        async with database.session_scope() as session:
            actor = await actor_for(session, ADMIN_LOGIN)
            inventory = ExternalInventory(session, actor, source)
            decision = await ListingRevalidation(session, actor, inventory).evaluate(
                candidate.listing_id,
                IntendedAction.RECOMMEND,
                NOW + timedelta(minutes=1),
            )
            return decision.outcome

    async def refresh() -> None:
        async with database.session_scope() as session:
            actor = await actor_for(session, ADMIN_LOGIN)
            await ExternalInventory(session, actor, source).refresh(
                "EB-FAKE-001", at=NOW + timedelta(minutes=1)
            )

    first = asyncio.create_task(recommend())
    await asyncio.wait_for(source.entered.wait(), timeout=2)
    second = asyncio.create_task(refresh())
    await asyncio.sleep(0.05)
    assert source.concurrent_retrieves == 1
    source.release.set()
    assert await asyncio.wait_for(first, timeout=2) == "Eligible"
    await asyncio.wait_for(second, timeout=2)
    assert source.max_concurrent_retrieves == 1


class BlockingSource(FakeInventorySource):
    def __init__(self) -> None:
        super().__init__()
        self.block_next = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.concurrent_retrieves = 0
        self.max_concurrent_retrieves = 0

    async def retrieve(
        self, scope: ExternalInventoryScope, source_listing_id: str
    ) -> dict[str, object]:
        self.concurrent_retrieves += 1
        self.max_concurrent_retrieves = max(
            self.max_concurrent_retrieves, self.concurrent_retrieves
        )
        try:
            if self.block_next:
                self.block_next = False
                self.entered.set()
                await self.release.wait()
            return await super().retrieve(scope, source_listing_id)
        finally:
            self.concurrent_retrieves -= 1


class FailingExternal:
    async def search(self, criteria: InventorySearchCriteria):  # noqa: ANN201
        del criteria
        raise AssertionError("external fallback must not run when own inventory matches")
