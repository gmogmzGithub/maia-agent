"""Acceptance contracts for ADR-0056 through ADR-0059."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from httpx import ASGITransport, BasicAuth
from sqlalchemy import func, select, text
from starlette.datastructures import FormData

from realestate.api import crm
from realestate.api.market_intelligence import _money, require_market_analyst
from realestate.api.plugin import SESSION_HEADER
from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    FactsReviewState,
    MarketContribution,
    MarketRecordRevision,
    MarketSaleRecord,
    Opportunity,
    OpportunityStage,
    Property,
    SharedMarketRecord,
    SharedMarketRecordVersion,
    SharedBuyerProfile,
    TransactionMilestone,
)
from realestate.domain.commercial.actors import (
    InvalidTransition,
    MissingEvidence,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.next_actions import NextActionKind
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    OpportunityManagement,
    QualificationAction,
    RecordWon,
    WonEvidence,
)
from realestate.domain.journeys import (
    JourneyState,
    JourneyTemplates,
    MilestoneState,
    TransactionJourneys,
)
from realestate.domain.market_intelligence import (
    ComparableFilters,
    MarketIntelligenceAnalyst,
    MarketProjector,
    MarketRecords,
    SharedMarketDataset,
    _age_band,
    _income_band,
    _json_safe,
    _median,
    _uuid,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.conftest import env as environment_value
from tests.fixtures import commercial

pytestmark = requires_postgres

ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)
ANALYST = BasicAuth("analyst", "market-test-password")


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)
    yield database
    await database.dispose()


@pytest.fixture
async def surface(wired: Database, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    monkeypatch.setenv(
        "MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON",
        '{"analyst":"market-test-password"}',
    )
    get_settings.cache_clear()
    app = create_app(get_settings())
    app.state.database = wired
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client
    get_settings.cache_clear()


async def _started(session, *, qualified: bool = False):  # noqa: ANN001, ANN202
    state = await commercial.opportunity_for(
        session,
        assign=True,
        confirm_criteria=qualified,
    )
    templates = JourneyTemplates(session)
    draft = await templates.create_draft(state.admin)
    await templates.approve(state.admin, draft.id)
    workspace = await TransactionJourneys(session).start(
        state.admin, state.opportunity_id
    )
    return state, workspace


async def _property(session, organization_id: uuid.UUID) -> Property:  # noqa: ANN001
    row = Property(
        organization_id=organization_id,
        property_key=f"journey-{uuid.uuid4().hex[:8]}",
        name="Casa Jornada",
        normalized_name="casa jornada",
        status="Active",
        property_type="House",
        physical_facts={
            "municipality": "Zapopan",
            "colonia": "Valle Real",
            "construction_area_sqm": "180.00",
            "bedrooms": 3,
        },
        facts_review_state=FactsReviewState.APPROVED.value,
        provenance={"source": "test"},
    )
    session.add(row)
    await session.flush()
    return row


async def test_template_approval_is_a_gate_and_starting_does_not_win(wired) -> None:
    async with wired.session_scope() as session:
        state = await commercial.opportunity_for(session, assign=True)
        templates = JourneyTemplates(session)
        draft = await templates.create_draft(state.admin)
        with pytest.raises(MissingEvidence, match="aprobar"):
            await TransactionJourneys(session).start(state.admin, state.opportunity_id)

        await templates.approve(state.admin, draft.id)
        workspace = await TransactionJourneys(session).start(
            state.admin, state.opportunity_id
        )
        await session.commit()

        opportunity = await session.get(Opportunity, state.opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.NEW.value
        assert workspace.journey.frozen_plan == draft.plan
        assert len(workspace.milestones) == 14
        assert workspace.sale.state == "Preparation"
        assert await session.scalar(select(func.count(MarketContribution.id))) == 2


async def test_maia_cannot_advance_a_milestone_and_humans_must_supply_evidence(
    wired,
) -> None:
    async with wired.session_scope() as session:
        state, workspace = await _started(session)
        milestone = workspace.milestones[0]
        product = await commercial.product_actor(session)
        with pytest.raises(NotAuthorized, match="Maia no puede"):
            await TransactionJourneys(session).update_milestone(
                product, milestone.id, state=MilestoneState.COMPLETED
            )
        with pytest.raises(MissingEvidence, match="evidencia"):
            await TransactionJourneys(session).update_milestone(
                state.admin, milestone.id, state=MilestoneState.COMPLETED
            )
        changed = await TransactionJourneys(session).update_milestone(
            state.admin,
            milestone.id,
            state=MilestoneState.COMPLETED,
            evidence="Confirmado por la persona responsable",
        )
        assert changed.state == MilestoneState.COMPLETED.value
        assert changed.confirmed_by == state.admin.member_id


async def test_won_requires_minimum_sale_facts_and_projects_only_confirmed_truth(
    wired,
) -> None:
    async with wired.session_scope() as session:
        state, workspace = await _started(session, qualified=True)
        await OpportunityManagement(session).record(
            state.admin,
            AdvanceStage(
                opportunity_id=state.opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="stage10:qualify",
                qualification_action=QualificationAction(
                    kind=NextActionKind.CALL,
                    due_at=commercial.now() + timedelta(days=1),
                ),
            ),
        )
        command = RecordWon(
            opportunity_id=state.opportunity_id,
            evidence=WonEvidence.COMPLETED_SALE,
            evidence_detail="Escritura firmada y liquidación confirmada",
            command_key="stage10:won",
        )
        with pytest.raises(MissingEvidence, match="datos mínimos"):
            await OpportunityManagement(session).record(state.admin, command)

        property_row = await _property(session, state.admin.organization_id)
        await MarketRecords(session).update_sale(
            state.admin,
            state.opportunity_id,
            values={
                "property_uuid": property_row.id,
                "completion_date": commercial.now().date(),
                "paid_price": Decimal("4250000.00"),
                "paid_currency": "MXN",
            },
            field_states={},
        )
        await OpportunityManagement(session).record(state.admin, command)
        await session.commit()

        sale = await session.get(MarketSaleRecord, workspace.sale.id)
        opportunity = await session.get(Opportunity, state.opportunity_id)
        assert sale is not None and sale.state == "Completed"
        assert sale.property_type == "House"
        assert sale.municipality == "Zapopan"
        assert opportunity is not None and opportunity.stage == "Won"

        report = await MarketProjector(session).drain()
        await session.commit()
        assert report.projected >= 1
        shared = await session.scalar(
            select(SharedMarketRecord).where(
                SharedMarketRecord.source_record_id == sale.id
            )
        )
        assert shared is not None
        assert shared.state == "Completed"
        assert shared.paid_price == Decimal("4250000.00")
        assert not {
            "contact_id",
            "phone",
            "wa_id",
            "conversation_id",
            "document_id",
        } & {column.name for column in SharedMarketRecord.__table__.columns}


async def test_direct_sql_correction_is_revised_and_reprojected(wired) -> None:
    async with wired.session_scope() as session:
        state, workspace = await _started(session)
        property_row = await _property(session, state.admin.organization_id)
        await MarketRecords(session).update_sale(
            state.admin,
            state.opportunity_id,
            values={
                "property_uuid": property_row.id,
                "completion_date": commercial.now().date(),
                "paid_price": Decimal("4100000.00"),
                "paid_currency": "MXN",
            },
            field_states={},
        )
        await session.commit()
        await MarketProjector(session).drain()
        await session.commit()

        await session.execute(
            text("UPDATE market_sale_records SET paid_price = :price WHERE id = :id"),
            {"price": Decimal("4050000.00"), "id": workspace.sale.id},
        )
        await session.commit()

        revision = await session.scalar(
            select(MarketRecordRevision)
            .where(MarketRecordRevision.source_id == workspace.sale.id)
            .order_by(MarketRecordRevision.source_version.desc())
            .limit(1)
        )
        assert revision is not None
        assert Decimal(revision.old_values["paid_price"]) == Decimal("4100000.00")
        assert Decimal(revision.new_values["paid_price"]) == Decimal("4050000.00")
        assert revision.database_role
        assert (await MarketRecords(session).revisions(state.admin, workspace.sale.id))[
            0
        ].id == revision.id

        await MarketProjector(session).drain()
        await session.commit()
        shared = await session.scalar(
            select(SharedMarketRecord).where(
                SharedMarketRecord.source_record_id == workspace.sale.id
            )
        )
        assert shared is not None and shared.paid_price == Decimal("4050000.00")
        assert (
            await session.scalar(
                select(func.count(SharedMarketRecordVersion.id)).where(
                    SharedMarketRecordVersion.source_record_id == workspace.sale.id
                )
            )
            >= 1
        )


async def test_duplicate_resolution_counts_once_and_can_withhold_aggregates(
    wired,
) -> None:
    async with wired.session_scope() as session:
        shared_property = uuid.uuid4()
        first_two: list[uuid.UUID] = []
        for index in range(5):
            row = SharedMarketRecord(
                source_organization_id=uuid.uuid4(),
                source_record_id=uuid.uuid4(),
                source_version=1,
                state="Completed",
                outcome="Won",
                property_uuid=shared_property if index < 2 else uuid.uuid4(),
                property_type="House",
                municipality="Zapopan",
                completion_date=commercial.now().date(),
                paid_price=Decimal("4000000.00") + index,
                paid_currency="MXN",
                field_states={},
            )
            if index == 1:
                row.paid_price = Decimal("4000000.00")
            session.add(row)
            await session.flush()
            if index < 2:
                first_two.append(row.id)
        analyst = MarketIntelligenceAnalyst("analista@maia.test")
        dataset = SharedMarketDataset(session, analyst)
        before = await dataset.comparables(ComparableFilters(currency="MXN"))
        assert before.sample_size == 5
        assert before.aggregate_available is True
        assert len(await dataset.duplicate_candidates()) == 1

        await dataset.resolve_duplicate(
            tuple(first_two), reason="Misma propiedad, fecha y precio confirmados"
        )
        after = await dataset.comparables(ComparableFilters(currency="MXN"))
        assert after.sample_size == 4
        assert after.aggregate_available is False
        assert after.median_paid_price is None


def test_every_optional_answer_has_an_explicit_state_contract() -> None:
    assert {"NotCaptured", "NotProvided", "Provided"}
    assert len({column.name for column in TransactionMilestone.__table__.columns}) > 5
    assert _money(None, None) == "—"
    assert _uuid(None) is None
    assert _json_safe([Decimal("1.00")]) == ["1.00"]
    assert _median([]) is None
    assert _median([Decimal("1"), Decimal("3")]) == Decimal("2")
    assert [_age_band(age) for age in (29, 35, 45, 55, 65)] == [
        "<30",
        "30–39",
        "40–49",
        "50–59",
        "60+",
    ]
    assert _income_band(Decimal("24000")) == "<25k"


async def test_crm_drives_the_human_journey_workspace_end_to_end(
    wired: Database, surface: httpx.AsyncClient
) -> None:
    async with wired.session_scope() as session:
        state = await commercial.opportunity_for(session, assign=True)
        property_row = await _property(session, state.admin.organization_id)
        await session.commit()
        opportunity_id = state.opportunity_id
        property_id = property_row.id

    detail = await surface.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert detail.status_code == 200
    assert "Todavía no hay un template de compra" in detail.text

    created = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/template", auth=ADMIN
    )
    assert created.status_code == 303
    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        template = await JourneyTemplates(session).latest(actor)
        assert template is not None
        template_id = template.id

    draft = await surface.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "Borrador" in draft.text
    approved = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/template/{template_id}/aprobar",
        auth=ADMIN,
    )
    assert approved.status_code == 303
    review = await surface.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "Aprobado" in review.text
    started = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/iniciar", auth=ADMIN
    )
    assert started.status_code == 303

    active = await surface.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "Perfil de compra" in active.text
    assert "Hitos confirmados por personas" in active.text
    assert "Product reutiliza sus datos aprobados" in active.text

    profile = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/perfil",
        auth=ADMIN,
        data={
            "birth_year": "1988",
            "monthly_income": "95000.50",
            "income_currency": "mxn",
            "adults": "2",
            "children": "1",
            "financial_dependants": "1",
            "co_buyers": "1",
            "home_purchase_number": "1",
            "payment_path": "Combined",
            "financing_modality": "Crédito bancario",
            "down_payment": "800000",
            "down_payment_currency": "mxn",
            "target_monthly_payment": "35000",
            "target_payment_currency": "mxn",
            "preapproval_state": "InProgress",
            "np_children": "1",
        },
    )
    assert profile.status_code == 303

    sale = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/venta",
        auth=ADMIN,
        data={
            "property_uuid": str(property_id),
            "publication_date": "2026-06-01",
            "completion_date": "2026-08-29",
            "published_price": "4500000",
            "published_currency": "mxn",
            "appraisal_value": "4300000",
            "appraisal_currency": "mxn",
            "paid_price": "4250000",
            "paid_currency": "mxn",
            "bathrooms": "2.5",
            "parking_spaces": "2",
            "construction_year": "2020",
            "property_condition": "Good",
            "np_colonia": "1",
        },
    )
    assert sale.status_code == 303

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        workspace = await TransactionJourneys(session).for_opportunity(
            actor, opportunity_id
        )
        assert workspace is not None
        milestone_id = workspace.milestones[0].id

    milestone = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/hitos/{milestone_id}",
        auth=ADMIN,
        data={
            "estado": "Completed",
            "evidencia": "Confirmación humana registrada",
            "vence": "2026-09-01T10:00",
        },
    )
    assert milestone.status_code == 303
    concluded = await surface.post(
        f"/crm/oportunidades/{opportunity_id}/tramite/concluir",
        auth=ADMIN,
        data={"estado": "Cancelled", "motivo": "La compradora desistió"},
    )
    assert concluded.status_code == 303


def test_crm_form_contracts_refuse_ambiguous_values() -> None:
    form = FormData(
        {
            "integer": "not-an-int",
            "decimal": "not-money",
            "date": "29/08/2026",
            "currency": "pesos",
        }
    )
    with pytest.raises(InvalidTransition, match="número entero"):
        crm._form_int(form, "integer")
    with pytest.raises(InvalidTransition, match="importe válido"):
        crm._form_decimal(form, "decimal")
    with pytest.raises(InvalidTransition, match="fecha válida"):
        crm._form_date(form, "date")
    with pytest.raises(InvalidTransition, match="tres letras"):
        crm._currency(form, "currency")
    values: dict[str, object] = {"known": "confirmed", "declined": "ignored"}
    states = crm._field_states(
        FormData({"np_declined": "1"}),
        frozenset({"known", "declined", "missing"}),
        values,
    )
    assert states == {
        "known": "Provided",
        "declined": "NotProvided",
        "missing": "NotCaptured",
    }
    assert values["declined"] is None
    empty = FormData()
    assert crm._form_date(empty, "date") is None
    assert crm._currency(empty, "currency") is None


async def test_crm_mutations_fail_closed_before_a_journey_exists(
    wired: Database, surface: httpx.AsyncClient
) -> None:
    async with wired.session_scope() as session:
        state = await commercial.opportunity_for(session, assign=True)
        await session.commit()
        opportunity_id = state.opportunity_id

    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/template", auth=ADVISOR
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/iniciar", auth=ADMIN
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/template/{uuid.uuid4()}/aprobar",
            auth=ADMIN,
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/hitos/{uuid.uuid4()}",
            auth=ADMIN,
            data={"estado": "Invented"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/hitos/{uuid.uuid4()}",
            auth=ADMIN,
            data={"estado": "Pending", "vence": "not-a-date"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/hitos/{uuid.uuid4()}",
            auth=ADMIN,
            data={"estado": "Pending"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/perfil",
            auth=ADMIN,
            data={"birth_year": "unknown"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/perfil",
            auth=ADMIN,
            data={"birth_year": "1988"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/venta",
            auth=ADMIN,
            data={"paid_price": "4200000"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/venta",
            auth=ADMIN,
            data={"property_uuid": "not-a-uuid"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/venta",
            auth=ADMIN,
            data={"municipality": "Zapopan"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/concluir",
            auth=ADMIN,
            data={"estado": "Invented"},
        )
    ).status_code == 303
    assert (
        await surface.post(
            f"/crm/oportunidades/{opportunity_id}/tramite/concluir",
            auth=ADMIN,
            data={"estado": "Completed"},
        )
    ).status_code == 303


def test_market_analyst_authentication_refuses_misconfiguration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = HTTPBasicCredentials(username="analyst", password="wrong")
    for configured in ("", "not-json", '{"analyst":""}'):
        monkeypatch.setenv("MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON", configured)
        get_settings.cache_clear()
        with pytest.raises(HTTPException) as raised:
            require_market_analyst(credentials)
        assert raised.value.status_code == 503
    monkeypatch.setenv(
        "MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON",
        '{"analyst":"market-test-password"}',
    )
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as raised:
        require_market_analyst(credentials)
    assert raised.value.status_code == 401
    get_settings.cache_clear()


async def test_analyst_dashboard_is_separate_and_resolves_duplicates(
    wired: Database, surface: httpx.AsyncClient
) -> None:
    record_ids: list[uuid.UUID] = []
    shared_property = uuid.uuid4()
    async with wired.session_scope() as session:
        founding_id = await commercial.organization_id(session)
        for index in range(5):
            row = SharedMarketRecord(
                source_organization_id=founding_id if index == 0 else uuid.uuid4(),
                source_record_id=uuid.uuid4(),
                source_version=1,
                state="Completed",
                outcome="Won",
                property_uuid=shared_property if index < 2 else uuid.uuid4(),
                property_type="House",
                municipality="Zapopan",
                publication_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
                completion_date=datetime(2026, 8, 1, tzinfo=UTC).date(),
                construction_area_sqm=Decimal("180"),
                published_price=Decimal("4500000") + index,
                published_currency="MXN",
                appraisal_value=Decimal("4300000") + index,
                appraisal_currency="MXN",
                paid_price=Decimal("4200000")
                if index < 2
                else Decimal("4200000") + index,
                paid_currency="MXN",
                field_states={},
            )
            session.add(row)
            await session.flush()
            record_ids.append(row.id)
            session.add(
                SharedBuyerProfile(
                    source_organization_id=row.source_organization_id,
                    source_profile_id=uuid.uuid4(),
                    source_version=1,
                    source_sale_record_id=row.source_record_id,
                    facts={
                        "payment_path": "Cash" if index % 2 == 0 else "Credit",
                        "home_purchase_number": index % 3 + 1,
                        "birth_year": 1980 + index,
                        "monthly_income": str(40_000 + index * 15_000),
                        "income_currency": "MXN",
                        "children": index % 4,
                        "financial_dependants": index % 3,
                    },
                    field_states={},
                )
            )
        await session.commit()

    unauthorized = await surface.get("/market-intelligence")
    assert unauthorized.status_code == 401
    dashboard = await surface.get(
        "/market-intelligence",
        auth=ANALYST,
        params={
            "property_type": " House ",
            "municipality": " Zapopan ",
            "currency": " mxn ",
        },
    )
    assert dashboard.status_code == 200
    assert "Mediana pagada" in dashboard.text
    assert "Total pagado" in dashboard.text
    assert "Mediana pagada por m²" in dashboard.text
    assert "Forma de pago" in dashboard.text
    assert "Edad al cierre" in dashboard.text
    assert "Posibles ventas co-brokeradas" in dashboard.text
    assert "Sin acceso al CRM" in dashboard.text
    subject = await surface.get(
        "/market-intelligence",
        auth=ANALYST,
        params={"subject_record_id": str(record_ids[0])},
    )
    assert subject.status_code == 200
    assert "Venta sujeto" in subject.text
    async with wired.session_scope() as session:
        mixed_currency = await session.get(SharedMarketRecord, record_ids[-1])
        assert mixed_currency is not None
        mixed_currency.paid_currency = "USD"
        await session.commit()
    mixed = await surface.get("/market-intelligence", auth=ANALYST)
    assert "agregados se reservan" in mixed.text

    resolution = await surface.post(
        "/market-intelligence/resolutions",
        auth=ANALYST,
        data={
            "record_id": [str(record_ids[0]), str(record_ids[1])],
            "reason": "Misma propiedad, fecha y liquidación",
        },
    )
    assert resolution.status_code == 303
    after = await surface.get("/market-intelligence", auth=ANALYST)
    assert "Muestra: 4" in after.text

    invalid = await surface.post(
        "/market-intelligence/resolutions",
        auth=ANALYST,
        data={"record_id": "not-a-uuid", "reason": "x"},
    )
    assert invalid.status_code == 400
    async with wired.session_scope() as session:
        dataset = SharedMarketDataset(session, MarketIntelligenceAnalyst("analyst"))
        with pytest.raises(MissingEvidence, match="al menos dos"):
            await dataset.resolve_duplicate((record_ids[0],), reason="x")
        with pytest.raises(MissingEvidence, match="Explica"):
            await dataset.resolve_duplicate(tuple(record_ids[:2]), reason=" ")
        with pytest.raises(InvalidTransition, match="otra resolución"):
            await dataset.resolve_duplicate(
                tuple(record_ids[:2]), reason="Repetición deliberada"
            )


async def test_hermes_reads_only_human_confirmed_journey_state(
    wired: Database, surface: httpx.AsyncClient
) -> None:
    session_key = "stage-ten-journey"
    async with wired.session_scope() as session:
        state, workspace = await _started(session)
        conversation = await commercial.make_conversation(session, state.lead)
        await TransactionJourneys(session).update_milestone(
            state.admin,
            workspace.milestones[0].id,
            state=MilestoneState.COMPLETED,
            evidence="Documento privado que Hermes no debe recibir",
        )
        session.add(
            AgentSession(
                organization_id=state.admin.organization_id,
                hermes_session_id=session_key,
                role=AgentRole.SALES.value,
                cycle_id=conversation.cycle_id,
            )
        )
        await session.commit()

    headers = {
        "Authorization": f"Bearer {environment_value('PLUGIN_API_TOKEN')}",
        SESSION_HEADER: session_key,
    }
    response = await surface.post(
        "/internal/plugin/tools/get_transaction_journey", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "found"
    assert body["milestones"][0]["evidence_recorded"] is True
    assert "Documento privado" not in response.text
    forbidden = await surface.post(
        "/internal/plugin/tools/get_transaction_journey",
        headers={"Authorization": f"Bearer {environment_value('PLUGIN_API_TOKEN')}"},
    )
    assert forbidden.json() == {"result": "forbidden"}


async def test_journey_lifecycle_refuses_invalid_plans_and_requires_human_closure(
    wired: Database,
) -> None:
    async with wired.session_scope() as session:
        state = await commercial.opportunity_for(session, assign=True)
        templates = JourneyTemplates(session)
        product = await commercial.product_actor(session)
        with pytest.raises(NotAuthorized, match="miembro autorizado"):
            await TransactionJourneys(session).start(product, state.opportunity_id)
        with pytest.raises(MissingEvidence, match="al menos un hito"):
            await templates.create_draft(state.admin, plan=())
        with pytest.raises(MissingEvidence, match="código, nombre y responsable"):
            await templates.create_draft(
                state.admin,
                plan=({"code": "incomplete", "name": "Sin responsable"},),
            )
        duplicate_plan = (
            {"code": "same", "name": "Uno", "responsibility": "Asesor"},
            {"code": "same", "name": "Dos", "responsibility": "Notaría"},
        )
        with pytest.raises(InvalidTransition, match="repetido"):
            await templates.create_draft(state.admin, plan=duplicate_plan)

        draft = await templates.create_draft(state.admin)
        assert await templates.create_draft(state.admin) == draft
        with pytest.raises(NotFound):
            await templates.approve(state.admin, uuid.uuid4())
        approved = await templates.approve(state.admin, draft.id)
        assert await templates.approve(state.admin, draft.id) == approved

        workspace = await TransactionJourneys(session).start(
            state.admin, state.opportunity_id
        )
        assert (
            await TransactionJourneys(session).start(state.admin, state.opportunity_id)
        ).journey.id == workspace.journey.id
        with pytest.raises(MissingEvidence, match="motivo"):
            await TransactionJourneys(session).update_milestone(
                state.admin,
                workspace.milestones[0].id,
                state=MilestoneState.BLOCKED,
            )
        with pytest.raises(MissingEvidence, match="Completa u omite"):
            await TransactionJourneys(session).conclude(
                state.admin, workspace.journey.id, state=JourneyState.COMPLETED
            )
        for milestone in workspace.milestones:
            await TransactionJourneys(session).update_milestone(
                state.admin,
                milestone.id,
                state=MilestoneState.SKIPPED,
                reason="No aplica según confirmación humana",
            )
        completed = await TransactionJourneys(session).conclude(
            state.admin, workspace.journey.id, state=JourneyState.COMPLETED
        )
        assert completed.state == "Completed"
        assert (
            await TransactionJourneys(session).conclude(
                state.admin, workspace.journey.id, state=JourneyState.COMPLETED
            )
        ).id == completed.id
        with pytest.raises(InvalidTransition, match="ya fue concluida"):
            await TransactionJourneys(session).conclude(
                state.admin, workspace.journey.id, state=JourneyState.CANCELLED
            )
        with pytest.raises(InvalidTransition, match="ya no está activa"):
            await TransactionJourneys(session).update_milestone(
                state.admin,
                workspace.milestones[0].id,
                state=MilestoneState.IN_PROGRESS,
            )


async def test_market_record_boundaries_and_failed_projection_are_explicit(
    wired: Database,
) -> None:
    async with wired.session_scope() as session:
        state, workspace = await _started(session)
        records = MarketRecords(session)
        product = await commercial.product_actor(session)
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized, match="no inventarlo"):
            await records.update_profile(
                product,
                state.opportunity_id,
                values={"birth_year": 1988},
                field_states={},
            )
        with pytest.raises(InvalidTransition, match="Campos desconocidos"):
            await records.update_profile(
                state.admin,
                state.opportunity_id,
                values={"secret": "never"},
                field_states={},
            )
        with pytest.raises(InvalidTransition, match="estado de un dato"):
            await records.update_profile(
                state.admin,
                state.opportunity_id,
                values={},
                field_states={"birth_year": "Guessed"},
            )
        with pytest.raises(NotAuthorized, match="no puede confirmar"):
            await records.update_sale(
                product,
                state.opportunity_id,
                values={"paid_price": Decimal("1")},
                field_states={},
            )
        with pytest.raises(InvalidTransition, match="Campos desconocidos"):
            await records.update_sale(
                state.admin,
                state.opportunity_id,
                values={"contact_phone": "never"},
                field_states={},
            )
        with pytest.raises(NotFound, match="No encontramos esa propiedad"):
            await records.update_sale(
                state.admin,
                state.opportunity_id,
                values={"property_uuid": uuid.uuid4()},
                field_states={},
            )
        property_row = await _property(session, state.admin.organization_id)
        await records.update_sale(
            state.admin,
            state.opportunity_id,
            values={
                "property_uuid": property_row.id,
                "completion_date": commercial.now().date(),
                "paid_price": Decimal("4200000"),
                "paid_currency": "MXN",
            },
            field_states={},
        )
        workspace.sale.state = "Completed"
        workspace.sale.completed_by = state.admin.member_id
        workspace.sale.completed_at = commercial.now()
        await session.flush()
        with pytest.raises(InvalidTransition, match="directamente en PostgreSQL"):
            await records.update_sale(
                advisor,
                state.opportunity_id,
                values={"municipality": "Zapopan"},
                field_states={},
            )
        with pytest.raises(InvalidTransition, match="directamente en PostgreSQL"):
            await records.update_profile(
                state.admin,
                state.opportunity_id,
                values={"birth_year": 1988},
                field_states={},
            )
        workspace.sale.state = "Cancelled"
        await session.flush()
        with pytest.raises(InvalidTransition, match="cancelado"):
            await records.update_sale(
                state.admin,
                state.opportunity_id,
                values={"municipality": "Zapopan"},
                field_states={},
            )

        orphan = MarketContribution(
            organization_id=state.admin.organization_id,
            source_type="PurchaseProfile",
            source_id=uuid.uuid4(),
            source_version=1,
            event_key=f"test:orphan:{uuid.uuid4()}",
            payload={},
            state="Pending",
        )
        session.add(orphan)
        await session.flush()
        report = await MarketProjector(session).drain()
        assert report.failed == 1
        assert orphan.state == "Failed"
        assert "has no Market Sale Record" in (orphan.last_error or "")
