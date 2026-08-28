"""Provider-owned Message Template lifecycle and fail-closed capture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from realestate.channels.whatsapp.templates import MetaTemplateSource
from realestate.db.engine import Database
from realestate.db.models import (
    ApprovedMessageTemplate,
    ConsentCategory,
    ConsentRecord,
    ConsentState,
)
from realestate.domain.engagement.consent import DEVELOPMENT_SCOPE, MarketingConsent
from realestate.domain.engagement.templates import (
    TemplateObservation,
    TemplateRegistry,
    TemplateSourceUnavailable,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    opportunity_for,
    provision,
    reset,
)

pytestmark = requires_postgres
NOW = datetime(2026, 8, 28, 18, tzinfo=UTC)


class FakeTemplateSource:
    def __init__(self, observations: tuple[TemplateObservation, ...] = ()) -> None:
        self.observations = observations
        self.configured = True

    async def list_templates(self) -> tuple[TemplateObservation, ...]:
        return self.observations


class BrokenTemplateSource:
    configured = True

    async def list_templates(self) -> tuple[TemplateObservation, ...]:
        raise RuntimeError("provider unavailable")


def observation(
    *,
    status: str = "APPROVED",
    category: str = "MARKETING",
    body: str = "Tenemos una opción nueva.",
) -> TemplateObservation:
    return TemplateObservation(
        waba_id="waba-fixture",
        provider_template_id="provider-1",
        name="nueva_coincidencia",
        language="es_MX",
        category=category,
        status=status,
        components=({"type": "BODY", "text": body},),
        quality="GREEN",
        provider_api_version="v25.0",
    )


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
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


async def test_sync_records_provider_truth_and_retirement_without_local_approval(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        result = await TemplateRegistry(session).synchronize(
            admin, FakeTemplateSource((observation(),)), at=NOW
        )
        evidence = await TemplateRegistry(session).approved(
            organization_id=admin.organization_id,
            name="nueva_coincidencia",
            language="es_MX",
            category=ConsentCategory.MARKETING,
            at=NOW,
        )
        await session.commit()

    assert result.approved_marketing == 1
    assert evidence is not None
    assert evidence.body_text == "Tenemos una opción nueva."

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        retired = await TemplateRegistry(session).synchronize(
            admin, FakeTemplateSource(), at=NOW + timedelta(minutes=1)
        )
        row = await session.scalar(select(ApprovedMessageTemplate))
        assert row is not None
        assert row.provider_status == "Deleted"
        assert row.retired_at == NOW + timedelta(minutes=1)
        assert retired.retired == 1
        assert (
            await TemplateRegistry(session).approved(
                organization_id=admin.organization_id,
                name="nueva_coincidencia",
                language="es_MX",
                category=ConsentCategory.MARKETING,
                at=NOW + timedelta(minutes=1),
            )
            is None
        )


async def test_wrong_category_status_language_and_stale_observation_are_denied(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await TemplateRegistry(session).synchronize(
            admin,
            FakeTemplateSource((observation(status="PAUSED", category="UTILITY"),)),
            at=NOW,
        )
        registry = TemplateRegistry(session)
        assert (
            await registry.approved(
                organization_id=admin.organization_id,
                name="nueva_coincidencia",
                language="en_US",
                category=ConsentCategory.MARKETING,
                at=NOW,
            )
            is None
        )

        await registry.synchronize(
            admin, FakeTemplateSource((observation(),)), at=NOW
        )
        assert (
            await registry.approved(
                organization_id=admin.organization_id,
                name="nueva_coincidencia",
                language="es_MX",
                category=ConsentCategory.UTILITY,
                at=NOW,
            )
            is None
        )
        assert (
            await registry.approved(
                organization_id=admin.organization_id,
                name="nueva_coincidencia",
                language="es_MX",
                category=ConsentCategory.MARKETING,
                at=NOW + timedelta(days=2),
            )
            is None
        )
async def test_parameterized_template_is_denied_until_binding_is_implemented(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await TemplateRegistry(session).synchronize(
            admin,
            FakeTemplateSource((observation(body="Hola {{1}}, tenemos una opción."),)),
            at=NOW,
        )
        assert (
            await TemplateRegistry(session).approved(
                organization_id=admin.organization_id,
                name="nueva_coincidencia",
                language="es_MX",
                category=ConsentCategory.MARKETING,
                at=NOW,
            )
            is None
        )


async def test_unconfigured_source_and_unapproved_consent_capture_fail_closed(
    database: Database,
) -> None:
    source = FakeTemplateSource()
    source.configured = False
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(TemplateSourceUnavailable):
            await TemplateRegistry(session).synchronize(admin, source, at=NOW)
        decision = await MarketingConsent(session).capture(
            admin,
            lead_id=admin.organization_id,
            scope="DevelopmentAnnouncements",
            evidence="asserted by administrator",
        )
    assert decision.granted is False
    assert decision.reason == "ConsentCaptureFoundationNotApproved"

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(TemplateSourceUnavailable):
            await TemplateRegistry(session).synchronize(
                admin, BrokenTemplateSource(), at=NOW
            )
        result = await TemplateRegistry(session).synchronize(
            admin,
            FakeTemplateSource(
                (
                    TemplateObservation(
                        waba_id="",
                        provider_template_id=None,
                        name="",
                        language="",
                        category="UNKNOWN",
                        status="UNKNOWN",
                        components=(),
                        quality=None,
                        provider_api_version="v25.0",
                    ),
                    TemplateObservation(
                        waba_id="waba-fixture",
                        provider_template_id="unknown-category",
                        name="categoria_desconocida",
                        language="es_MX",
                        category="UNKNOWN",
                        status="UNKNOWN",
                        components=({"type": "BODY", "text": "Texto"},),
                        quality=None,
                        provider_api_version="v25.0",
                    ),
                )
            ),
            at=NOW,
        )
        assert result.observed == 2


async def test_consent_expiry_evidence_scope_and_capture_path_are_explicit(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, wa_id="5213312399999")
        consent = MarketingConsent(session)
        session.add(
            ConsentRecord(
                lead_id=state.lead.id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="SyntheticFixture",
                business_name="Larevia",
                scope=DEVELOPMENT_SCOPE,
                notice_version="v1",
                evidence_locator="fixture://expired",
                expires_at=NOW,
                recorded_at=NOW - timedelta(minutes=3),
            )
        )
        await session.flush()
        expired = await consent.current(
            lead_id=state.lead.id, scope=DEVELOPMENT_SCOPE, at=NOW
        )

        session.add(
            ConsentRecord(
                lead_id=state.lead.id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="SyntheticFixture",
                scope=DEVELOPMENT_SCOPE,
                recorded_at=NOW - timedelta(minutes=2),
            )
        )
        await session.flush()
        incomplete = await consent.current(
            lead_id=state.lead.id, scope=DEVELOPMENT_SCOPE, at=NOW
        )

        session.add(
            ConsentRecord(
                lead_id=state.lead.id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="SyntheticFixture",
                business_name="Larevia",
                scope="AnotherScope",
                notice_version="v1",
                evidence_locator="fixture://mismatch",
                recorded_at=NOW - timedelta(minutes=1),
            )
        )
        await session.flush()
        mismatch = await consent.current(
            lead_id=state.lead.id, scope=DEVELOPMENT_SCOPE, at=NOW
        )
        capture = await MarketingConsent(session, capture_activated=True).capture(
            admin,
            lead_id=state.lead.id,
            scope=DEVELOPMENT_SCOPE,
            evidence="fixture",
        )

    assert expired.reason == "MarketingConsentExpired"
    assert incomplete.reason == "MarketingConsentEvidenceIncomplete"
    assert mismatch.reason == "MarketingConsentScopeMismatch"
    assert capture.reason == "ConsentCapturePathNotImplemented"


async def test_meta_adapter_reads_pagination_and_preserves_exact_language() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1",
                            "name": "nueva_coincidencia",
                            "language": "es_MX",
                            "category": "MARKETING",
                            "status": "APPROVED",
                            "components": [{"type": "BODY", "text": "Hola"}],
                            "quality_score": {"score": "GREEN"},
                        }
                    ],
                    "paging": {
                        "next": "https://graph.facebook.com/v25.0/waba/message_templates?after=2"
                    },
                },
            )
        return httpx.Response(200, json={"data": []})

    source = MetaTemplateSource(
        access_token="secret",
        waba_id="waba",
        graph_version="v25.0",
        base_url="https://graph.facebook.com",
        transport=httpx.MockTransport(handler),
    )
    try:
        rows = await source.list_templates()
    finally:
        await source.aclose()

    assert source.configured is True
    assert len(rows) == 1
    assert rows[0].language == "es_MX"
    assert rows[0].body_text == "Hola"
    assert seen[0].headers["Authorization"] == "Bearer secret"
    assert len(seen) == 2


async def test_meta_adapter_rejects_untrusted_pagination_host() -> None:
    source = MetaTemplateSource(
        access_token="secret",
        waba_id="waba",
        graph_version="v25.0",
        base_url="https://graph.facebook.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [], "paging": {"next": "https://evil.test/steal"}},
            )
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="pagination host"):
            await source.list_templates()
    finally:
        await source.aclose()
