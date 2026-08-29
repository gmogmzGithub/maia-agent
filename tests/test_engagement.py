"""Stage 7 reactivation and Development campaign behavior."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from realestate.channels.whatsapp.payload import InboundMessage
from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    ApprovedMessageTemplate,
    CampaignAudienceMember,
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    DevelopmentCampaign,
    Development,
    FactsReviewState,
    Opportunity,
    OpportunityOrigin,
    OutboxMessage,
    PropertyNeed,
    ReactivationCandidate,
    SuppressionRecord,
)
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateDevelopment,
    ReviewDevelopmentFacts,
)
from realestate.domain.commercial.opportunities import (
    DormantReason,
    OpportunityManagement,
    RecordDormant,
)
from realestate.domain.commercial.actors import InvalidTransition, NotFound
from realestate.domain.commercial.needs import CriterionStatement, PropertyNeeds
from realestate.domain.engagement.campaigns import (
    ActivateCampaign,
    CampaignDenied,
    Campaigns,
    CancelCampaign,
    PauseCampaign,
    PlanCampaign,
)
from realestate.domain.engagement.audience import Audience
from realestate.domain.engagement.consent import BROAD_REAL_ESTATE_SCOPE
from realestate.domain.engagement.reactivation import (
    AuthorizeReactivation,
    Reactivation,
    RejectReactivation,
    RevokeReactivation,
)
from realestate.domain.engagement.templates import TemplateObservation, TemplateRegistry
from realestate.domain.inbox import InboxService
from realestate.domain.outbound import (
    DeliveryDenied,
    DenialReason,
    OutboundMessaging,
)
from realestate.worker.engagement import EngagementWorker, outside_send_hours
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    make_conversation,
    opportunity_for,
    provision,
    reset,
)
from tests.fixtures.public_site import publish_listing
from tests.fixtures import commercial

pytestmark = requires_postgres
NOW = datetime(2026, 8, 28, 18, tzinfo=UTC)  # noon in Mexico City


class FakeTemplates:
    configured = True

    def __init__(self, *items: tuple[str, str]) -> None:
        self.items = items

    async def list_templates(self) -> tuple[TemplateObservation, ...]:
        return tuple(
            TemplateObservation(
                waba_id="waba-fixture",
                provider_template_id=f"meta-{name}",
                name=name,
                language="es_MX",
                category="MARKETING",
                status="APPROVED",
                components=({"type": "BODY", "text": body},),
                quality="GREEN",
                provider_api_version="v25.0",
            )
            for name, body in self.items
        )


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        for table_name in (
            "marketing_touches",
            "campaign_audience_members",
            "development_campaigns",
            "reactivation_candidates",
            "approved_message_templates",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        await reset(session)
        await reset_property_inventory(session)
        await reset(session, members=True)
        await provision(session)
    yield database
    await database.dispose()


async def foundation(database: Database, *, contacts: int = 1):
    states = []
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(
            session,
            admin,
            f"reactivacion-{uuid.uuid4().hex[:6]}",
            price=Decimal("4000000"),
        )
        catalog = CatalogAdministration(session)
        development = await catalog.record(
            admin,
            CreateDevelopment(
                development_key=f"desarrollo-{uuid.uuid4().hex[:6]}",
                name="Desarrollo sintético",
                facts={
                    "service_area": "Zapopan",
                    "authority": "fixture",
                    "marketing_authority_confirmed": True,
                },
                provenance={"kind": "SyntheticFixture"},
                command_key=f"development:{uuid.uuid4().hex}",
            ),
        )
        await catalog.record(
            admin,
            ReviewDevelopmentFacts(
                development_id=development.subject_id,
                review_state=FactsReviewState.APPROVED,
                facts={
                    "service_area": "Zapopan",
                    "authority": "fixture",
                    "marketing_authority_confirmed": True,
                },
                command_key=f"development-review:{uuid.uuid4().hex}",
            ),
        )
        await TemplateRegistry(session).synchronize(
            admin,
            FakeTemplates(
                ("nueva_coincidencia", "Encontramos una opción nueva para ti."),
                ("nuevo_desarrollo", "Tenemos un desarrollo que podría interesarte."),
            ),
            at=NOW,
        )
        for index in range(contacts):
            state = await opportunity_for(
                session,
                wa_id=f"5213312300{index:03d}",
                confirm_criteria=True,
            )
            conversation = await make_conversation(
                session, state.lead, started_at=NOW - timedelta(days=10)
            )
            session.add(
                ConsentRecord(
                    organization_id=state.lead.organization_id,
                    lead_id=state.lead.id,
                    category=ConsentCategory.MARKETING.value,
                    state=ConsentState.GRANTED.value,
                    source="SyntheticFixture",
                    evidence="Casilla separada aceptada",
                    business_name="Larevia",
                    scope=BROAD_REAL_ESTATE_SCOPE,
                    notice_version="fixture-v1",
                    evidence_locator=f"fixture://consent/{index}",
                    recorded_at=NOW - timedelta(days=1),
                )
            )
            states.append((state, conversation))
        await session.commit()
    return listing, development.subject_id, states


async def test_candidate_is_reviewed_and_never_auto_sends(database: Database) -> None:
    listing, _, _ = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        rows = await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        assert len(rows) == 1
        assert rows[0].match_kind == "Approximate"
        assert rows[0].explanation
        assert await session.scalar(select(func.count(OutboxMessage.id))) == 0
        rejected = await Reactivation(session, admin).reject(
            RejectReactivation(rows[0].candidate_id, "No es suficientemente relevante"),
            at=NOW,
        )
        await session.commit()
    assert rejected.status == "Rejected"


async def test_missing_consent_denies_admin_authorization(database: Database) -> None:
    listing, _, states = await foundation(database)
    async with database.session_scope() as session:
        await session.execute(
            text("DELETE FROM consent_records WHERE lead_id = :lead"),
            {"lead": states[0][0].lead.id},
        )
        admin = await actor_for(session, ADMIN_LOGIN)
        candidate = (
            await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        )[0]
        denied = await Reactivation(session, admin, activation_approved=True).authorize(
            AuthorizeReactivation(
                candidate.candidate_id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Coincidencia revisada",
            ),
            at=NOW,
        )
        await session.commit()
    assert denied.status == "Denied"
    assert denied.review_reason == "MarketingConsentMissing"


async def test_revocation_before_worker_prevents_outbound(database: Database) -> None:
    listing, _, _ = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        candidate = (
            await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        )[0]
        authorized = await Reactivation(
            session, admin, activation_approved=True
        ).authorize(
            AuthorizeReactivation(
                candidate.candidate_id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Coincidencia revisada",
            ),
            at=NOW,
        )
        assert authorized.status == "Authorized"
        revoked = await Reactivation(session, admin).revoke(
            RevokeReactivation(candidate.candidate_id, "Inventario retirado"), at=NOW
        )
        await session.commit()
    assert revoked.status == "Revoked"
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0
    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(OutboxMessage.id))) == 0


async def test_reactivation_reply_stops_sequence_and_attributes_new_opportunity(
    database: Database,
) -> None:
    listing, _, states = await foundation(database)
    state, _ = states[0]
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await OpportunityManagement(session).record(
            admin,
            RecordDormant(
                opportunity_id=state.opportunity_id,
                reason=DormantReason.AWAITING_NEW_INVENTORY,
                revisit_condition="Cuando exista inventario nuevo compatible.",
                command_key="fixture:dormant",
                at=NOW - timedelta(days=1),
            ),
        )
        candidate = (
            await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        )[0]
        await Reactivation(session, admin, activation_approved=True).authorize(
            AuthorizeReactivation(
                candidate.candidate_id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Inventario nuevo compatible",
            ),
            at=NOW,
        )
        await session.commit()

    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0

    async with database.session_scope() as session:
        accepted = await InboxService(session).accept(
            InboundMessage(
                wamid="wamid.stage7.reply",
                from_wa_id=state.lead.wa_id,
                phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                message_type="text",
                sent_at=NOW + timedelta(minutes=1),
                text="Sí, me interesa verla",
                profile_name=None,
                raw={},
            )
        )
        candidate_row = await session.scalar(select(ReactivationCandidate))
        opportunities = list(
            await session.scalars(
                select(Opportunity).where(Opportunity.contact_id == state.contact_id)
            )
        )
        origin = await session.scalar(
            select(OpportunityOrigin).where(
                OpportunityOrigin.opportunity_id == accepted.opportunity_id
            )
        )
    assert candidate_row is not None and candidate_row.status == "Responded"
    assert len(opportunities) == 2
    assert origin is not None and origin.source == "Campaign"
    assert origin.campaign is not None and origin.campaign.startswith("reactivation:")


async def test_campaign_preview_is_dry_and_explains_stale_and_suppressed_exclusions(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database, contacts=3)
    async with database.session_scope() as session:
        stale = await session.get(PropertyNeed, states[1][0].need_id)
        assert stale is not None
        stale.status = "Stale"
        stale.became_stale_at = NOW
        session.add(
            SuppressionRecord(
                organization_id=states[2][0].lead.organization_id,
                lead_id=states[2][0].lead.id,
                reason="ExplicitOptOut",
                evidence="No me escribas",
                recorded_at=NOW,
            )
        )
        admin = await actor_for(session, ADMIN_LOGIN)
        result = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Lanzamiento sintético",
                property_need_ids=tuple(
                    state.need_id for state, _ in states if state.need_id
                ),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                service_area_contains="Zapopan",
            ),
            at=NOW,
        )
        before = list(
            await session.scalars(
                select(CampaignAudienceMember).where(
                    CampaignAudienceMember.campaign_id == result.campaign_id
                )
            )
        )
        preview = await Campaigns(session, admin).preview(result.campaign_id, at=NOW)
        after = list(
            await session.scalars(
                select(CampaignAudienceMember).where(
                    CampaignAudienceMember.campaign_id == result.campaign_id
                )
            )
        )
        await session.commit()
    assert [item.status for item in preview].count("Included") == 1
    reasons = {reason for item in preview for reason in item.reasons}
    assert {"PropertyNeedStale", "Suppressed"} <= reasons
    assert [(row.id, row.status) for row in before] == [
        (row.id, row.status) for row in after
    ]


async def test_audience_deduplicates_contacts_and_audits_activation_changes(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database, contacts=2)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        original = await PropertyNeeds(session).snapshot(states[0][0].need_id)
        duplicate = await PropertyNeeds(session).open(
            admin, contact_id=states[0][0].contact_id
        )
        await PropertyNeeds(session).record(
            admin,
            duplicate.id,
            [
                CriterionStatement.recorded(name, value, evidence="SyntheticFixture")
                for name, value in original.confirmed.items()
            ],
            now=NOW,
        )
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Audiencia con cambio",
                property_need_ids=(
                    states[0][0].need_id,
                    duplicate.id,
                    states[1][0].need_id,
                ),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                frequency_cap=2,
            ),
            at=NOW,
        )
        assert [item.status for item in plan.audience].count("Included") == 2
        assert any(item.reasons == ("DuplicateContact",) for item in plan.audience)

        session.add(
            SuppressionRecord(
                organization_id=states[1][0].lead.organization_id,
                lead_id=states[1][0].lead.id,
                reason="ExplicitOptOut",
                evidence="No me escribas",
                recorded_at=NOW + timedelta(seconds=30),
            )
        )
        activated = await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW + timedelta(minutes=1)
        )
        audit = await session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ActivateDevelopmentCampaign")
            .where(AuditEvent.subject_id == str(plan.campaign_id))
        )
        await session.commit()

    assert [item.status for item in activated.audience].count("Included") == 1
    assert audit is not None
    assert audit.details["audience_changes"] == [
        {
            "reference": next(
                item.reference
                for item in activated.audience
                if item.reasons == ("Suppressed",)
            ),
            "before_status": "Included",
            "after_status": "Excluded",
            "before_reasons": [],
            "after_reasons": ["Suppressed"],
        }
    ]


async def test_audience_rejects_invalid_explicit_criteria_with_named_reasons(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database)
    need_id = states[0][0].need_id
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Criterios inválidos",
                property_need_ids=(need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW,
        )
        campaign = await session.get(DevelopmentCampaign, plan.campaign_id)
        assert campaign is not None
        campaign.audience_criteria = {
            "property_need_ids": ["no-es-uuid", str(uuid.uuid4()), str(need_id)],
            "exclude_property_need_ids": [str(need_id)],
            "transaction_intents": ["Rent"],
            "service_area_contains": "Monterrey",
        }
        preview = await Audience(session, admin).resolve(plan.campaign_id, NOW)
        assert preview[0].reasons == (
            "ExcludedByAdministrator",
            "TransactionIntentMismatch",
            "ServiceAreaMismatch",
        )
        campaign.audience_criteria = {"property_need_ids": "not-a-list"}
        assert await Audience(session, admin).resolve(plan.campaign_id, NOW) == ()
        with pytest.raises(NotFound):
            await Audience(session, admin).resolve(uuid.uuid4(), NOW)


async def test_campaign_pause_cancel_retry_and_mid_campaign_optout(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database, contacts=2)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Dos destinatarios",
                property_need_ids=tuple(
                    state.need_id for state, _ in states if state.need_id
                ),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                service_area_contains="Zapopan",
                frequency_cap=2,
            ),
            at=NOW,
        )
        campaigns = Campaigns(session, admin, activation_approved=True)
        await campaigns.activate(ActivateCampaign(plan.campaign_id), at=NOW)
        await campaigns.pause(
            PauseCampaign(plan.campaign_id, "Revisión de calidad"), at=NOW
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        remaining_lead = await session.scalar(
            select(CampaignAudienceMember.lead_id)
            .where(CampaignAudienceMember.campaign_id == plan.campaign_id)
            .where(CampaignAudienceMember.status == "Included")
            .limit(1)
        )
        assert remaining_lead is not None
        session.add(
            SuppressionRecord(
                organization_id=await commercial.organization_id(session),
                lead_id=remaining_lead,
                reason="ExplicitOptOut",
                evidence="Baja",
                recorded_at=NOW + timedelta(minutes=1),
            )
        )
        await session.commit()
    assert (
        await EngagementWorker(database, activation_approved=True).tick(
            now=NOW + timedelta(minutes=1)
        )
        == 1
    )
    assert (
        await EngagementWorker(database, activation_approved=True).tick(
            now=NOW + timedelta(minutes=1)
        )
        == 0
    )

    async with database.session_scope() as session:
        members = list(
            await session.scalars(
                select(CampaignAudienceMember).order_by(CampaignAudienceMember.id)
            )
        )
        assert {row.status for row in members} == {"Queued", "Denied"}
        assert any(row.reasons == ["Suppressed"] for row in members)
        assert await session.scalar(select(func.count(OutboxMessage.id))) == 1
        admin = await actor_for(session, ADMIN_LOGIN)
        completed = await session.get(DevelopmentCampaign, plan.campaign_id)
        assert completed is not None and completed.status == "Completed"

    # A separate draft can be cancelled before execution; cancellation is
    # terminal and a worker restart cannot request new outbound work.
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        second = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Cancelada",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                frequency_cap=3,
            ),
            at=NOW,
        )
        await Campaigns(session, admin).cancel(
            CancelCampaign(second.campaign_id, "Decisión administrativa"), at=NOW
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0


async def test_template_language_retirement_and_frequency_cap_deny(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(CampaignDenied, match="plantilla"):
            await Campaigns(session, admin).plan(
                PlanCampaign(
                    development_id=development_id,
                    name="Idioma no aprobado",
                    property_need_ids=(states[0][0].need_id,),
                    template_name="nuevo_desarrollo",
                    template_language="en_US",
                    content_preview="Development news",
                ),
                at=NOW,
            )
        first = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Primera",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW,
        )
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(first.campaign_id), at=NOW
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        second = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Segunda",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW + timedelta(minutes=1),
        )
        assert second.audience[0].status == "Excluded"
        assert second.audience[0].reasons == ("FrequencyCapReached",)


async def test_cancel_after_queue_quarantines_delivery(database: Database) -> None:
    _, development_id, states = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Cancelar antes de Meta",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW,
        )
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW
        )
        await session.commit()

    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        cancelled = await Campaigns(session, admin).cancel(
            CancelCampaign(plan.campaign_id, "Detener antes de entregar"),
            at=NOW + timedelta(minutes=1),
        )
        assert cancelled.status == "Cancelled"
        await session.commit()

    async with database.session_scope() as session:
        message = await session.scalar(select(OutboxMessage))
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(
            message, now=NOW + timedelta(minutes=2)
        )
    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.ENGAGEMENT_NOT_ACTIVE


async def test_delivery_requires_campaign_audience_evidence(database: Database) -> None:
    _, development_id, states = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Evidencia obligatoria",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW,
        )
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        member = await session.scalar(select(CampaignAudienceMember))
        assert member is not None
        await session.delete(member)
        await session.commit()
    async with database.session_scope() as session:
        message = await session.scalar(select(OutboxMessage))
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(message, now=NOW)
    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.ELIGIBILITY_EVIDENCE_MISSING


async def test_delivery_rechecks_reactivation_candidate_state(database: Database) -> None:
    listing, _, _ = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        candidate = (
            await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        )[0]
        await Reactivation(session, admin, activation_approved=True).authorize(
            AuthorizeReactivation(
                candidate.candidate_id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Revisada",
            ),
            at=NOW,
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        row = await session.get(ReactivationCandidate, candidate.candidate_id)
        assert row is not None
        row.status = "Revoked"
        row.review_reason = "Cambio antes de Meta"
        await session.commit()
    async with database.session_scope() as session:
        message = await session.scalar(select(OutboxMessage))
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(message, now=NOW)
    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.ENGAGEMENT_NOT_ACTIVE


async def test_concurrent_workers_never_duplicate_a_campaign_member(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database, contacts=2)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Ejecución concurrente",
                property_need_ids=tuple(
                    state.need_id for state, _ in states if state.need_id
                ),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                frequency_cap=2,
            ),
            at=NOW,
        )
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW
        )
        await session.commit()

    first = await asyncio.gather(
        EngagementWorker(database, activation_approved=True).tick(now=NOW),
        EngagementWorker(database, activation_approved=True).tick(now=NOW),
    )
    processed = sum(first)
    while processed < 2:
        processed += await EngagementWorker(database, activation_approved=True).tick(
            now=NOW
        )
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0

    async with database.session_scope() as session:
        keys = list(await session.scalars(select(OutboxMessage.idempotency_key)))
    assert len(keys) == len(set(keys)) == 2


async def test_real_activation_gate_defaults_to_denied(database: Database) -> None:
    _, development_id, states = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Sólo vista previa",
                property_need_ids=(states[0][0].need_id,),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
            ),
            at=NOW,
        )
        with pytest.raises(CampaignDenied, match="activación real"):
            await Campaigns(session, admin).activate(
                ActivateCampaign(plan.campaign_id), at=NOW
            )
        await session.rollback()

    assert await EngagementWorker(database).tick(now=NOW) == 0


async def test_campaign_invalid_plans_and_transitions_fail_closed(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database)
    need_id = states[0][0].need_id
    base = PlanCampaign(
        development_id=development_id,
        name="Validaciones",
        property_need_ids=(need_id,),
        template_name="nuevo_desarrollo",
        template_language="es_MX",
        content_preview="Tenemos un desarrollo que podría interesarte.",
    )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        campaigns = Campaigns(session, admin, activation_approved=True)
        with pytest.raises(NotFound):
            await campaigns.plan(replace(base, development_id=uuid.uuid4()), at=NOW)

        development = await session.get(Development, development_id)
        assert development is not None
        development.facts_review_state = FactsReviewState.PENDING.value
        with pytest.raises(CampaignDenied, match="datos"):
            await campaigns.plan(base, at=NOW)
        development.facts_review_state = FactsReviewState.APPROVED.value
        development.facts = {"service_area": "Zapopan"}
        with pytest.raises(CampaignDenied, match="autoridad"):
            await campaigns.plan(base, at=NOW)
        development.facts = {
            "service_area": "Zapopan",
            "marketing_authority_confirmed": True,
        }

        invalid = (
            replace(base, property_need_ids=()),
            replace(base, property_need_ids=tuple(uuid.uuid4() for _ in range(501))),
            replace(base, criteria_version="obsolete"),
            replace(base, quiet_hours_start=-1),
            replace(base, max_recipients=0),
            replace(base, frequency_cap=0),
            replace(base, template_name="no_aprobada"),
            replace(base, content_preview="Contenido diferente"),
        )
        for command in invalid:
            with pytest.raises(CampaignDenied):
                await campaigns.plan(command, at=NOW)

        plan = await campaigns.plan(base, at=NOW)
        await campaigns.activate(ActivateCampaign(plan.campaign_id), at=NOW)
        with pytest.raises(InvalidTransition, match="Sólo una campaña"):
            await campaigns.activate(ActivateCampaign(plan.campaign_id), at=NOW)
        await campaigns.pause(PauseCampaign(plan.campaign_id, "Pausa"), at=NOW)
        with pytest.raises(InvalidTransition, match="Sólo una campaña activa"):
            await campaigns.pause(PauseCampaign(plan.campaign_id, "Otra"), at=NOW)
        await campaigns.cancel(CancelCampaign(plan.campaign_id, "Fin"), at=NOW)
        again = await campaigns.cancel(CancelCampaign(plan.campaign_id, "Fin"), at=NOW)
        assert again.status == "Cancelled"
        with pytest.raises(NotFound, match="No encontramos"):
            await campaigns.pause(PauseCampaign(uuid.uuid4(), "Nada"), at=NOW)

        retired_plan = await campaigns.plan(replace(base, name="Retirada"), at=NOW)
        template = await session.scalar(
            select(ApprovedMessageTemplate).where(
                ApprovedMessageTemplate.template_name == "nuevo_desarrollo"
            )
        )
        assert template is not None
        template.provider_status = "Paused"
        with pytest.raises(CampaignDenied, match="plantilla"):
            await campaigns.activate(ActivateCampaign(retired_plan.campaign_id), at=NOW)


async def test_candidate_worker_handles_quiet_hours_missing_route_and_late_suppression(
    database: Database,
) -> None:
    listing, _, _ = await foundation(database)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        candidate = (
            await Reactivation(session, admin).discover(listing.listing_id, at=NOW)
        )[0]
        await Reactivation(session, admin, activation_approved=True).authorize(
            AuthorizeReactivation(
                candidate.candidate_id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Revisada",
            ),
            at=NOW,
        )
        await session.commit()

    quiet = datetime(2026, 8, 29, 3, tzinfo=UTC)
    assert await EngagementWorker(database, activation_approved=True).tick(now=quiet) == 0

    async with database.session_scope() as session:
        row = await session.get(ReactivationCandidate, candidate.candidate_id)
        assert row is not None
        row.conversation_id = None
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    # A second Candidate exercises an eligibility change after Admin review.
    async with database.session_scope() as session:
        first = await session.get(ReactivationCandidate, candidate.candidate_id)
        assert first is not None
        first.status = "Pending"
        first.reviewed_by = None
        first.reviewed_at = None
        first.review_reason = None
        admin = await actor_for(session, ADMIN_LOGIN)
        authorized = await Reactivation(
            session, admin, activation_approved=True
        ).authorize(
            AuthorizeReactivation(
                first.id,
                "nueva_coincidencia",
                "es_MX",
                "Encontramos una opción nueva para ti.",
                "Revisada de nuevo",
            ),
            at=NOW,
        )
        session.add(
            SuppressionRecord(
                organization_id=authorized.organization_id,
                lead_id=authorized.lead_id,
                reason="ExplicitOptOut",
                evidence="No",
                recorded_at=NOW,
            )
        )
        await session.commit()
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1
    async with database.session_scope() as session:
        denied = await session.get(ReactivationCandidate, candidate.candidate_id)
        assert denied is not None
        assert denied.status == "Denied"
        assert denied.review_reason == "Suppressed"


async def test_campaign_worker_handles_quiet_missing_route_frequency_and_late_optout(
    database: Database,
) -> None:
    _, development_id, states = await foundation(database, contacts=3)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        plan = await Campaigns(session, admin).plan(
            PlanCampaign(
                development_id=development_id,
                name="Guardas de ejecución",
                property_need_ids=tuple(
                    state.need_id for state, _ in states if state.need_id
                ),
                template_name="nuevo_desarrollo",
                template_language="es_MX",
                content_preview="Tenemos un desarrollo que podría interesarte.",
                frequency_cap=1,
            ),
            at=NOW,
        )
        await Campaigns(session, admin, activation_approved=True).activate(
            ActivateCampaign(plan.campaign_id), at=NOW
        )
        await session.commit()

    quiet = datetime(2026, 8, 29, 3, tzinfo=UTC)
    assert await EngagementWorker(database, activation_approved=True).tick(now=quiet) == 0
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1

    async with database.session_scope() as session:
        queued_contact = await session.scalar(
            select(CampaignAudienceMember.contact_id).where(
                CampaignAudienceMember.status == "Queued"
            )
        )
        remaining = list(
            await session.scalars(
                select(CampaignAudienceMember)
                .where(CampaignAudienceMember.status == "Included")
                .order_by(CampaignAudienceMember.id)
            )
        )
        assert queued_contact is not None and len(remaining) == 2
        remaining[0].contact_id = queued_contact
        remaining[1].conversation_id = None
        await session.commit()

    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 1
    assert await EngagementWorker(database, activation_approved=True).tick(now=NOW) == 0

    async with database.session_scope() as session:
        reasons = list(
            await session.scalars(
                select(CampaignAudienceMember.reasons).where(
                    CampaignAudienceMember.status == "Denied"
                )
            )
        )
    assert ["FrequencyCapReached"] in reasons
    assert ["VerifiedWhatsAppRouteMissing"] in reasons


def test_quiet_hours_fail_closed_for_bad_zone_and_cross_midnight() -> None:
    assert outside_send_hours(NOW, start=20, end=9, timezone="Bad/Zone") is True
    assert (
        outside_send_hours(
            datetime(2026, 8, 29, 3, tzinfo=UTC),
            start=20,
            end=9,
            timezone="America/Mexico_City",
        )
        is True
    )
    assert (
        outside_send_hours(NOW, start=20, end=9, timezone="America/Mexico_City")
        is False
    )
    assert (
        outside_send_hours(NOW, start=12, end=12, timezone="America/Mexico_City")
        is True
    )
