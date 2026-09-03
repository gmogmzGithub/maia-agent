"""The appointment tools at the authenticated plugin boundary (P-060, P-061).

``test_appointments.py`` covers the policy. This covers the seam in front of it,
which has its own rules and its own way of going wrong:

* Lead, Conversation, cycle, Broker, Calendar, duration, time zone and
  idempotency identity are resolved from the session binding — a Sales session
  bound to no cycle resolves to nothing, and an Administrative one never
  resolves to a Conversation at all;
* the model-facing argument set is exactly what TOOL-CONTRACTS.md lists. An
  extra key is rejected outright rather than ignored, because an ignored key
  reads to the Model as an accepted one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from realestate.api.plugin import SESSION_HEADER
from realestate.app import create_app
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    Appointment,
    CriterionSource,
    CriterionState,
    Conversation,
    Lead,
    LeadEngagementCycle,
    OutboundDecision,
    PropertyNeed,
    PropertyNeedCriterion,
)
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.commercial.intake import CommercialIntake
from realestate.domain.inbox import InboxService
from realestate.domain.properties import ArtifactStore, PropertyService
from tests.conftest import (
    DATABASE_URL,
    age_pending_inbox,
    env,
    requires_postgres,
    reset_property_inventory,
)
from tests.fixtures import commercial, webhooks
from tests.fixtures.stubs import SCHEDULE, StubCalendar

FIXTURES = Path(__file__).parents[1] / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = requires_postgres

SALES_SESSION = "sess-sales-slots"
ADMIN_SESSION = "sess-admin-slots"
UNBOUND_SALES_SESSION = "sess-sales-no-cycle"

SLOTS_PATH = "/internal/plugin/tools/get_available_slots"
BOOK_PATH = "/internal/plugin/tools/book_appointment"
CANCEL_PATH = "/internal/plugin/tools/cancel_appointment"
NEED_PATH = "/internal/plugin/tools/record_property_need"
JOURNEY_PATH = "/internal/plugin/tools/get_transaction_journey"

LEAD_MESSAGE = (
    "Quiero comprar en Zapopan, de 4 a 5 millones, este trimestre; "
    "necesito 3 recámaras y jardín."
)


@pytest.fixture
async def wired(tmp_path: Path):
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset_property_inventory(session)
        for model in (
            AgentSession,
            Conversation,
            LeadEngagementCycle,
            Lead,
        ):
            await session.execute(delete(model))
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    # A shared stub answers both the calendar port and the directory the
    # scheduling module now takes, which is the honest double for the
    # one-calendar setup these suites are about.
    app.state.calendar = StubCalendar()
    app.state.calendars = app.state.calendar
    app.state.appointment_policy = AppointmentPolicy(
        schedule=SCHEDULE,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
        day_of_reminder_hour=9,
    )

    async with database.session_scope() as session:
        # Stage 3 refuses a visit without a Responsible Advisor who has an
        # authoritative calendar, and reconciliation has to happen before the
        # first inbound message because intake assigns as it opens.
        await commercial.provision_bookable_team(session)
        organization = await commercial.organization_id(session)
        await PropertyService(
            session, app.state.artifacts, organization_id=organization
        ).accept_upload("casa-roble.md", V1, actor_id="developer")
        message = parse_webhook(
            webhooks.text_message(wamid="w-slots", body=LEAD_MESSAGE)
        ).messages[0]
        await InboxService(session).accept(message)

    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        session.add_all(
            [
                AgentSession(
                    organization_id=conversation.organization_id,
                    hermes_session_id=SALES_SESSION,
                    role=AgentRole.SALES.value,
                    cycle_id=conversation.cycle_id,
                ),
                AgentSession(
                    organization_id=conversation.organization_id,
                    hermes_session_id=UNBOUND_SALES_SESSION,
                    role=AgentRole.SALES.value,
                ),
                AgentSession(
                    organization_id=conversation.organization_id,
                    hermes_session_id=ADMIN_SESSION,
                    role=AgentRole.ADMINISTRATIVE.value,
                    channel_key="telegram:1",
                ),
            ]
        )
        await session.commit()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app
    await database.dispose()


def headers(session_id: str = SALES_SESSION) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {env('PLUGIN_API_TOKEN')}",
        SESSION_HEADER: session_id,
    }


async def ask_slots(client, session_id: str = SALES_SESSION, **body):  # noqa: ANN001
    return await client.post(
        SLOTS_PATH,
        headers=headers(session_id),
        json={"reference": "casa-roble", **body},
    )


async def book(client, session_id: str = SALES_SESSION, **body):  # noqa: ANN001
    return await client.post(BOOK_PATH, headers=headers(session_id), json=body)


async def cancel(client, session_id: str = SALES_SESSION, **body):  # noqa: ANN001
    return await client.post(CANCEL_PATH, headers=headers(session_id), json=body)


async def record_need(client, session_id: str = SALES_SESSION, **body):  # noqa: ANN001
    return await client.post(NEED_PATH, headers=headers(session_id), json=body)


def a_candidate(payload: dict) -> str:
    assert payload["result"] == "available", payload
    return payload["candidates"][0]["start"]


# -- Authority ------------------------------------------------------------------


async def test_a_sales_session_bound_to_a_cycle_may_ask_for_slots(wired) -> None:
    client, _ = wired

    body = (await ask_slots(client)).json()

    assert body["result"] == "available"
    assert body["candidates"]


async def test_a_sales_session_with_no_cycle_resolves_to_nothing(wired) -> None:
    """The local exercise script's binding must not reach a Lead's calendar."""
    client, _ = wired

    assert (await ask_slots(client, UNBOUND_SALES_SESSION)).json() == {
        "result": "forbidden"
    }


async def test_an_administrative_session_cannot_ask_for_slots(wired) -> None:
    client, _ = wired

    assert (await ask_slots(client, ADMIN_SESSION)).json() == {"result": "forbidden"}


async def test_an_unknown_session_cannot_ask_for_slots(wired) -> None:
    client, _ = wired

    assert (await ask_slots(client, "sess-nobody")).json() == {"result": "forbidden"}


async def test_a_session_bound_to_a_cycle_with_no_conversation_resolves_to_nothing(
    wired,
) -> None:
    client, app = wired
    async with app.state.database.session_scope() as session:
        await session.execute(delete(Conversation))
        await session.commit()

    assert (await ask_slots(client)).json() == {"result": "forbidden"}


async def test_an_administrative_session_cannot_book(wired) -> None:
    client, _ = wired

    body = (
        await book(
            client,
            ADMIN_SESSION,
            reference="casa-roble",
            start="2026-08-10T16:00:00-06:00",
        )
    ).json()

    assert body == {"result": "forbidden"}


async def test_an_administrative_session_cannot_cancel(wired) -> None:
    client, _ = wired

    body = (await cancel(client, ADMIN_SESSION)).json()

    assert body == {"result": "forbidden"}


async def test_an_administrative_session_cannot_record_a_sales_need(wired) -> None:
    client, _ = wired

    body = (
        await record_need(
            client,
            ADMIN_SESSION,
            criteria=[
                {
                    "name": "service_area",
                    "value": "Zapopan",
                    "source": "ContactStated",
                    "evidence": "Zapopan",
                }
            ],
        )
    ).json()

    assert body == {"result": "forbidden"}


async def test_the_plugin_credential_is_required_for_sales_tools(wired) -> None:
    client, _ = wired

    for path in (SLOTS_PATH, BOOK_PATH, CANCEL_PATH):
        response = await client.post(
            path,
            headers={"Authorization": "Bearer wrong", SESSION_HEADER: SALES_SESSION},
            json={"reference": "casa-roble", "start": "2026-08-10T16:00:00-06:00"},
        )
        assert response.status_code == 401

    response = await client.post(
        NEED_PATH,
        headers={"Authorization": "Bearer wrong", SESSION_HEADER: SALES_SESSION},
        json={
            "criteria": [
                {
                    "name": "service_area",
                    "value": "Zapopan",
                    "source": "ContactStated",
                    "evidence": "Zapopan",
                }
            ]
        },
    )
    assert response.status_code == 401


async def test_an_unconfigured_plugin_token_is_a_503_not_an_open_door(
    wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing credential must never degrade into "no authentication needed"."""
    client, _ = wired
    get_settings.cache_clear()
    monkeypatch.setenv("PLUGIN_API_TOKEN", "")

    response = await client.post(
        SLOTS_PATH, headers=headers(), json={"reference": "casa-roble"}
    )

    assert response.status_code == 503
    assert "PLUGIN_API_TOKEN" in response.json()["detail"]
    get_settings.cache_clear()


# -- The frozen argument set ----------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"lead_id": "abc"},
        {"limit": 5},
        {"time_zone": "UTC"},
        {"calendar_id": "broker@example.com"},
        {"horizon_days": 30},
    ],
)
async def test_a_slot_query_refuses_any_argument_outside_the_contract(
    wired, extra: dict
) -> None:
    client, _ = wired

    assert (await ask_slots(client, **extra)).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"end": "2026-08-10T17:30:00-06:00"},
        {"duration_minutes": 90},
        {"lead_id": "abc"},
    ],
)
async def test_a_booking_refuses_any_argument_outside_the_contract(
    wired, extra: dict
) -> None:
    client, _ = wired

    response = await book(
        client, reference="casa-roble", start="2026-08-10T16:00:00-06:00", **extra
    )

    assert response.status_code == 422


@pytest.mark.parametrize("clock", ["7:00", "07:0", "0700", "25:00:00"])
async def test_a_time_bound_that_is_not_local_hh_mm_is_refused(
    wired, clock: str
) -> None:
    client, _ = wired

    assert (await ask_slots(client, time_from=clock)).status_code == 422


async def test_a_missing_property_reference_is_refused(wired) -> None:
    client, _ = wired

    response = await client.post(SLOTS_PATH, headers=headers(), json={})

    assert response.status_code == 422


# -- Property Need --------------------------------------------------------------


async def test_contact_stated_criteria_flow_to_the_bound_property_need(wired) -> None:
    client, app = wired
    criteria = [
        ("transaction_intent", "Buy"),
        ("service_area", "Zapopan"),
        ("economic_range", "4 a 5 millones MXN"),
        ("horizon", "Este trimestre"),
        ("essential_requirements", "3 recámaras y jardín"),
    ]

    response = await record_need(
        client,
        criteria=[
            {
                "name": name,
                "value": value,
                "source": "ContactStated",
                "evidence": LEAD_MESSAGE,
            }
            for name, value in criteria
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "recorded"
    assert body["ready_for_qualification"] is True
    assert body["missing_required"] == []
    assert body["evidence_downgraded"] == []
    async with app.state.database.session_scope() as session:
        stored = list(await session.scalars(select(PropertyNeedCriterion)))
    assert {row.name: row.value for row in stored} == dict(criteria)
    assert {row.state for row in stored} == {CriterionState.CONFIRMED.value}
    assert {row.source for row in stored} == {CriterionSource.CONTACT_STATED.value}


async def test_unsupported_contact_evidence_is_kept_pending(wired) -> None:
    client, app = wired

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "service_area",
                    "value": "Tlaquepaque",
                    "source": "ContactStated",
                    "evidence": "Quiero vivir en Tlaquepaque",
                }
            ],
        )
    ).json()

    assert body["result"] == "recorded"
    assert body["confirmed"] == []
    assert body["pending"] == ["service_area"]
    assert body["evidence_downgraded"] == ["service_area"]
    async with app.state.database.session_scope() as session:
        row = await session.scalar(
            select(PropertyNeedCriterion).where(
                PropertyNeedCriterion.name == "service_area",
                PropertyNeedCriterion.value == "Tlaquepaque",
                PropertyNeedCriterion.superseded_at.is_(None),
            )
        )
    assert row is not None
    assert row.state == CriterionState.PENDING.value
    assert row.source == CriterionSource.MODEL_INFERRED.value


async def test_spanish_transaction_intent_is_stored_as_canonical_product_truth(
    wired,
) -> None:
    client, app = wired

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "transaction_intent",
                    "value": "Compra",
                    "source": "ContactStated",
                    "evidence": LEAD_MESSAGE,
                }
            ],
        )
    ).json()

    assert body["result"] == "recorded"
    async with app.state.database.session_scope() as session:
        criterion = await session.scalar(
            select(PropertyNeedCriterion).where(
                PropertyNeedCriterion.name == "transaction_intent",
                PropertyNeedCriterion.superseded_at.is_(None),
            )
        )
        assert criterion is not None
        need = await session.get(PropertyNeed, criterion.property_need_id)
    assert criterion.value == "Buy"
    assert need is not None
    assert need.transaction_intent == "Buy"


async def test_unknown_transaction_intent_vocabulary_is_refused(wired) -> None:
    client, _ = wired

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "transaction_intent",
                    "value": "Algo inmobiliario",
                    "source": "ModelInferred",
                    "evidence": LEAD_MESSAGE,
                }
            ],
        )
    ).json()

    assert body == {
        "result": "invalid",
        "detail": "transaction_intent must use Buy, Rent, Sell, or LeaseOut.",
    }


async def test_property_need_contract_rejects_extra_authority_arguments(wired) -> None:
    client, _ = wired

    response = await record_need(
        client,
        criteria=[
            {
                "name": "service_area",
                "value": "Zapopan",
                "source": "ContactStated",
                "evidence": "Zapopan",
            }
        ],
        opportunity_id="model-supplied",
    )

    assert response.status_code == 422

    blank = await record_need(
        client,
        criteria=[
            {
                "name": "service_area",
                "value": "   ",
                "source": "ContactStated",
                "evidence": "Zapopan",
            }
        ],
    )
    assert blank.status_code == 422


async def test_property_need_rejects_duplicate_criterion_names(wired) -> None:
    client, _ = wired

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "service_area",
                    "value": "Zapopan",
                    "source": "ContactStated",
                    "evidence": LEAD_MESSAGE,
                },
                {
                    "name": "service_area",
                    "value": "Guadalajara",
                    "source": "ModelInferred",
                    "evidence": "El mensaje parece referirse al AMG.",
                },
            ],
        )
    ).json()

    assert body == {
        "result": "invalid",
        "detail": "Each property-need criterion may appear at most once.",
    }


async def test_property_need_refuses_a_closed_opportunity(wired) -> None:
    client, app = wired
    async with app.state.database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        opportunity = await CommercialIntake(session).opportunity_for_conversation(
            conversation
        )
        assert opportunity is not None
        opportunity.stage = "Lost"
        opportunity.lost_reason = "Unknown"
        opportunity.closed_at = datetime.now(tz=UTC)
        await session.commit()

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "service_area",
                    "value": "Zapopan",
                    "source": "ContactStated",
                    "evidence": LEAD_MESSAGE,
                }
            ],
        )
    ).json()

    assert body == {"result": "closed", "stage": "Lost"}


async def test_property_need_requires_an_attached_need(wired) -> None:
    client, app = wired
    async with app.state.database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        opportunity = await CommercialIntake(session).opportunity_for_conversation(
            conversation
        )
        assert opportunity is not None
        opportunity.property_need_id = None
        await session.commit()

    body = (
        await record_need(
            client,
            criteria=[
                {
                    "name": "service_area",
                    "value": "Zapopan",
                    "source": "ContactStated",
                    "evidence": LEAD_MESSAGE,
                }
            ],
        )
    ).json()

    assert body == {"result": "not_found"}


async def test_sales_journey_reports_absent_product_truth(wired) -> None:
    client, app = wired

    no_journey = await client.post(JOURNEY_PATH, headers=headers(), json={})
    assert no_journey.json() == {"result": "no_active_journey"}

    async with app.state.database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        opportunity = await CommercialIntake(session).opportunity_for_conversation(
            conversation
        )
        assert opportunity is not None
        await session.delete(opportunity)
        await session.commit()

    no_opportunity = await client.post(JOURNEY_PATH, headers=headers(), json={})
    assert no_opportunity.json() == {"result": "no_active_journey"}


async def test_untrusted_sessions_are_refused_across_the_tool_surface(wired) -> None:
    client, _ = wired
    untrusted = headers("sess-untrusted")
    cases = (
        ("/internal/plugin/tools/search_inventory", {"municipality": "Zapopan"}),
        (
            "/internal/plugin/tools/revalidate_external_listing",
            {"reference": "EB-SYNTHETIC", "intended_action": "Share"},
        ),
        ("/internal/plugin/tools/list_properties", {}),
        (
            "/internal/plugin/tools/resolve_pending_admin_work",
            {"reference": "WORK-1", "action": "Confirm"},
        ),
        ("/internal/plugin/tools/list_pending_admin_work", {}),
        (
            "/internal/plugin/tools/reschedule_appointment",
            {"start": "2026-08-10T16:00:00-06:00"},
        ),
        ("/internal/plugin/tools/request_human_handoff", {"reason": "Ayuda"}),
    )

    for path, payload in cases:
        response = await client.post(path, headers=untrusted, json=payload)
        assert response.status_code == 200, path
        assert response.json() == {"result": "forbidden"}, path


async def test_organization_specific_calendar_and_policy_sources_are_used(wired) -> None:
    client, app = wired
    calendar = app.state.calendars
    policy = app.state.appointment_policy
    resolved: list[str] = []

    class Calendars:
        async def for_organization(self, session, organization_id):  # noqa: ANN001, ANN202
            resolved.append(f"calendar:{organization_id}")
            return calendar

    class Policies:
        async def for_organization(self, session, organization_id):  # noqa: ANN001, ANN202
            resolved.append(f"policy:{organization_id}")
            return policy

    app.state.calendar_directories = Calendars()
    app.state.appointment_policies = Policies()

    body = (await ask_slots(client)).json()

    assert body["result"] == "available"
    assert [entry.split(":", 1)[0] for entry in resolved] == [
        "calendar",
        "policy",
    ]


async def test_revalidation_of_an_unknown_external_listing_is_not_found(wired) -> None:
    client, app = wired

    class EasyBrokerSource:
        source_name = "EasyBroker"

    app.state.easybroker = EasyBrokerSource()

    response = await client.post(
        "/internal/plugin/tools/revalidate_external_listing",
        headers=headers(),
        json={"reference": "EB-SYNTHETIC-MISSING", "intended_action": "Share"},
    )

    assert response.status_code == 200
    assert response.json() == {"result": "not_found"}


# -- Bounds --------------------------------------------------------------------


async def test_the_local_time_bounds_reach_the_policy(wired) -> None:
    client, _ = wired

    body = (await ask_slots(client, time_from="16:00", time_to="18:00")).json()

    assert body["result"] in {"available", "no_availability"}
    for candidate in body.get("candidates", []):
        hour = datetime.fromisoformat(candidate["start"]).hour
        assert 16 <= hour < 18


async def test_a_backwards_date_range_is_reported_rather_than_searched(wired) -> None:
    client, _ = wired
    today = datetime.now(tz=UTC).date()

    body = (
        await ask_slots(
            client,
            date_from=(today + timedelta(days=3)).isoformat(),
            date_to=today.isoformat(),
        )
    ).json()

    assert body["result"] == "temporarily_unavailable"
    assert "date_from is after date_to" in body["detail"]


async def test_one_sided_date_bounds_are_accepted(wired) -> None:
    client, _ = wired
    today = datetime.now(tz=UTC).date()

    only_from = (await ask_slots(client, date_from=today.isoformat())).json()
    only_to = (
        await ask_slots(client, date_to=(today + timedelta(days=5)).isoformat())
    ).json()

    assert only_from["result"] in {"available", "no_availability"}
    assert only_to["result"] in {"available", "no_availability"}


# -- Booking ---------------------------------------------------------------------


async def test_a_candidate_offered_by_the_slot_tool_can_be_booked(wired) -> None:
    client, app = wired
    start = a_candidate((await ask_slots(client)).json())

    body = (await book(client, reference="casa-roble", start=start)).json()

    assert body["result"] == "confirmed"
    assert body["appointment_reference"]
    assert app.state.calendar.created == [body["appointment_reference"]]


async def test_a_confirmed_appointment_can_be_cancelled_by_the_same_sales_session(
    wired,
) -> None:
    client, app = wired
    start = a_candidate((await ask_slots(client)).json())
    booked = (await book(client, reference="casa-roble", start=start)).json()
    await age_pending_inbox(app.state.database)
    async with app.state.database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        assert await InboxService(session).claim(conversation.id) is not None

    body = (await cancel(client)).json()

    assert body["result"] == "cancelled"
    assert body["lead_notified"] is True
    assert body["appointment_reference"] == booked["appointment_reference"]
    assert body["reschedule_prompt_required"] is True
    assert app.state.calendar.deleted == [f"evt-{booked['appointment_reference']}"]
    async with app.state.database.session_scope() as session:
        decision = (await session.execute(select(OutboundDecision))).scalar_one()
    assert len(decision.trigger_inbox_ids) == 1


async def test_the_attendee_name_is_display_only_and_carries_no_authority(
    wired,
) -> None:
    client, app = wired
    start = a_candidate((await ask_slots(client)).json())

    body = (
        await book(
            client, reference="casa-roble", start=start, attendee_name="Cliente Demo"
        )
    ).json()

    assert body["result"] == "confirmed"
    async with app.state.database.session_scope() as session:
        row = (await session.execute(select(Appointment))).scalar_one()
    assert row.attendee_name == "Cliente Demo"
    # The Lead the visit belongs to still comes from the binding, not the name.
    assert row.conversation_id is not None


async def test_a_blank_attendee_name_is_stored_as_absent_not_as_empty(wired) -> None:
    client, app = wired
    start = a_candidate((await ask_slots(client)).json())

    await book(client, reference="casa-roble", start=start, attendee_name="")

    async with app.state.database.session_scope() as session:
        row = (await session.execute(select(Appointment))).scalar_one()
    assert row.attendee_name is None


async def test_booking_the_same_candidate_twice_returns_the_same_appointment(
    wired,
) -> None:
    """The idempotency key is derived from trusted state, never from the Model."""
    client, app = wired
    start = a_candidate((await ask_slots(client)).json())

    first = (await book(client, reference="casa-roble", start=start)).json()
    second = (await book(client, reference="casa-roble", start=start)).json()

    assert first["appointment_reference"] == second["appointment_reference"]
    assert len(app.state.calendar.created) == 1


async def test_a_start_that_is_not_a_timestamp_is_refused(wired) -> None:
    client, _ = wired

    assert (
        await book(client, reference="casa-roble", start="mañana")
    ).status_code == 422
