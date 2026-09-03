"""WhatsApp → Maia → handoff or visit → Advisor → recorded result.

One scenario per branch of the stage's promise, driven end to end through the
real authenticated paths: a signed Meta webhook, the Inbox, the Lead worker, the
product tools the Model calls, the CRM an Advisor uses, and the internal alert
channel. Only the Model's judgement is scripted — every tool it calls is the real
one, so nothing here can pass because a fixture was generous.

No provider token is needed. Meta, Google Calendar and Telegram are stubbed at
their ports; everything above them is production code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select

from realestate.api import plugin as plugin_api
from realestate.api.plugin import SESSION_HEADER
from realestate.api import webhooks as webhook_api
from realestate.app import create_app
from realestate.config import Settings, get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AppointmentAttendance,
    AppointmentStatus,
    HandlingMode,
    HandoffStatus,
    HumanHandoffRequest,
    InternalAlert,
    NextAction,
    NextActionStatus,
    Opportunity,
    OutboxMessage,
    PropertyNeedCriterion,
)
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.commercial.handoff import ESCALATION_DELAY, HumanHandoff
from realestate.domain.properties import ArtifactStore
from realestate.worker.operations import OperationsWorker
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, age_pending_inbox, requires_postgres
from tests.fixtures import commercial, visits, webhooks
from tests.fixtures.stubs import SCHEDULE, StubTelegram, StubWhatsApp

pytestmark = requires_postgres

APP_SECRET = "e2e-app-secret"
PLUGIN_TOKEN = "e2e-plugin-token"
DURABLE_SESSION = "e2e-sales-session"
LEAD_WA_ID = "5213398765432"


def signed(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def post_webhook(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    body = json.dumps(payload).encode()
    return await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={
            "X-Hub-Signature-256": signed(body),
            "Content-Type": "application/json",
        },
    )


def nonce(html: str) -> str:
    match = re.search(r'name="clave" value="([0-9a-f]+)"', html)
    assert match, "every mutating form must render an idempotency key"
    return match.group(1)


@pytest.fixture
async def flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The whole product, wired to stubbed providers and a real database."""
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    get_settings.cache_clear()
    settings = Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET=APP_SECRET,
        META_VERIFY_TOKEN="e2e-verify",
        META_ACCESS_TOKEN="",
        META_PHONE_NUMBER_ID="",
        PLUGIN_API_TOKEN=PLUGIN_TOKEN,
        HERMES_DASHBOARD_SESSION_TOKEN="e2e-hermes",
        DEVELOPER_BASIC_CREDENTIALS_JSON=commercial.credentials_json(),
        GOOGLE_CALENDAR_CREDENTIALS="",
        GOOGLE_CALENDAR_ID="",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_ADMIN_IDS="",
        ARTIFACT_ROOT=str(tmp_path / "artifacts"),
        WORKER_ENABLED=False,
    )
    monkeypatch.setattr(webhook_api, "get_settings", lambda: settings)
    monkeypatch.setattr(plugin_api, "get_settings", lambda: settings)

    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await visits.reset(session)
        built = await visits.build(session, tmp_path / "artifacts")
        await session.commit()

    app = create_app(settings)
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    app.state.calendars = built.calendars
    app.state.appointment_policy = visits.policy()

    whatsapp = StubWhatsApp()
    telegram = StubTelegram()
    worker = WhatsAppWorker(
        database=database,
        hermes=object(),  # type: ignore[arg-type]
        whatsapp=whatsapp,  # type: ignore[arg-type]
        sales_profile="sales",
        schedule=SCHEDULE,
    )
    operations = OperationsWorker(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        schedule=SCHEDULE,
        day_of_reminder_hour=9,
        administrator_chat_ids=frozenset({"e2e-admin"}),
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield {
            "client": client,
            "database": database,
            "built": built,
            "whatsapp": whatsapp,
            "telegram": telegram,
            "worker": worker,
            "operations": operations,
            "app": app,
        }
    await database.dispose()
    get_settings.cache_clear()


def scripted(flow, turns):  # noqa: ANN001, ANN202
    """Replace only the Model's judgement.

    Each turn receives an authenticated HTTP client for the product tools and
    returns the reply text, so the tools it calls are the real ones and their
    refusals are real refusals.
    """
    client = flow["client"]
    remaining = iter(turns)

    async def run_turn(hermes, role_session, prompt, **kwargs):  # noqa: ANN001, ANN202
        durable = role_session.hermes_session_id or DURABLE_SESSION
        if not role_session.hermes_session_id:
            await kwargs["on_attached"](durable)
        headers = {
            "Authorization": f"Bearer {PLUGIN_TOKEN}",
            SESSION_HEADER: durable,
        }

        async def tool(name: str, body: dict) -> dict:
            response = await client.post(
                f"/internal/plugin/tools/{name}", json=body, headers=headers
            )
            assert response.status_code == 200, response.text
            return response.json()

        turn = next(remaining)
        text = await turn(tool, prompt)

        class Turn:
            def __init__(self, value: str) -> None:
                self.text = value

        return Turn(text)

    return run_turn


async def tick(flow, turns) -> None:  # noqa: ANN001
    """Run the Lead worker once with a scripted Model."""
    import realestate.worker.whatsapp as worker_module

    await age_pending_inbox(flow["database"])
    original = worker_module.run_turn
    worker_module.run_turn = scripted(flow, turns)  # type: ignore[assignment]
    try:
        await flow["worker"].tick()
    finally:
        worker_module.run_turn = original  # type: ignore[assignment]


# -- The conversation-to-CRM data pipeline -------------------------------


async def test_whatsapp_criteria_flow_through_maia_into_the_crm(flow) -> None:
    """Conversation facts cross the typed tool and appear in the operator view."""
    client = flow["client"]
    database = flow["database"]
    message = (
        "Quiero comprar en Zapopan, entre 8 y 10 millones, durante los próximos "
        "3 meses. Necesito 3 recámaras, jardín y espacio para home office."
    )
    accepted = await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.CRITERIA.1",
            body=message,
            from_wa_id=LEAD_WA_ID,
            profile_name="Lucía Demo",
        ),
    )
    assert accepted.json()["accepted"] == 1

    async def capture_need(tool, prompt):  # noqa: ANN001, ANN202
        result = await tool(
            "record_property_need",
            {
                "criteria": [
                    {
                        "name": "transaction_intent",
                        "value": "Buy",
                        "source": "ContactStated",
                        "evidence": message,
                    },
                    {
                        "name": "service_area",
                        "value": "Zapopan",
                        "source": "ContactStated",
                        "evidence": message,
                    },
                    {
                        "name": "economic_range",
                        "value": "8 a 10 millones MXN",
                        "source": "ContactStated",
                        "evidence": message,
                    },
                    {
                        "name": "horizon",
                        "value": "Próximos 3 meses",
                        "source": "ContactStated",
                        "evidence": message,
                    },
                    {
                        "name": "essential_requirements",
                        "value": "3 recámaras, jardín y home office",
                        "source": "ContactStated",
                        "evidence": message,
                    },
                ]
            },
        )
        assert result["result"] == "recorded", result
        assert result["ready_for_qualification"] is True
        return "Perfecto, ya entendí tu búsqueda. ¿Hay alguna zona de Zapopan que prefieras?"

    await tick(flow, [capture_need])
    assert len(flow["whatsapp"].sent) == 1

    async with database.session_scope() as session:
        opportunity = await session.scalar(select(Opportunity))
        criteria = list(await session.scalars(select(PropertyNeedCriterion)))
    assert opportunity is not None
    assert opportunity.stage == "InConversation"
    assert {row.name: row.value for row in criteria} == {
        "transaction_intent": "Buy",
        "service_area": "Zapopan",
        "economic_range": "8 a 10 millones MXN",
        "horizon": "Próximos 3 meses",
        "essential_requirements": "3 recámaras, jardín y home office",
    }
    assert {row.state for row in criteria} == {"Confirmed"}

    crm = await client.get(
        f"/crm/oportunidades/{opportunity.id}",
        auth=BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )
    assert crm.status_code == 200
    assert "Lucía Demo" in crm.text
    assert "8 a 10 millones MXN" in crm.text
    assert "3 recámaras, jardín y home office" in crm.text
    assert "Lo dijo el contacto" in crm.text


# -- The appointment branch ----------------------------------------------


async def test_whatsapp_to_confirmed_visit_to_recorded_outcome(flow) -> None:
    """The stage's central path, from a signed webhook to a recorded result."""
    client = flow["client"]
    database = flow["database"]
    built = flow["built"]

    accepted = await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.E2E.1",
            body="Hola, me interesa Casa Roble",
            from_wa_id=LEAD_WA_ID,
        ),
    )
    assert accepted.json()["accepted"] == 1

    async def answer(tool, prompt):  # noqa: ANN001, ANN202
        facts = await tool("get_property_information", {"reference": "Casa Roble"})
        assert facts["result"] == "found"
        return "Casa Roble tiene 4 recámaras. ¿Quieres agendar una visita?"

    await tick(flow, [answer])
    assert len(flow["whatsapp"].sent) == 1

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.E2E.2",
            body="Sí, quiero agendar una visita",
            from_wa_id=LEAD_WA_ID,
        ),
    )

    booked: dict[str, str] = {}

    async def book(tool, prompt):  # noqa: ANN001, ANN202
        slots = await tool("get_available_slots", {"reference": "Casa Roble"})
        assert slots["result"] == "available", slots
        assert slots["candidates"]
        result = await tool(
            "book_appointment",
            {
                "reference": "Casa Roble",
                "start": slots["candidates"][0]["start"],
                "attendee_name": "Ana Demo",
            },
        )
        assert result["result"] == "confirmed", result
        booked["reference"] = result["appointment_reference"]
        return "Listo, tu visita quedó agendada."

    await tick(flow, [book])

    # The Contact was told by *product* copy rendered from the persisted row.
    assert len(flow["whatsapp"].sent) == 2
    assert "quedó confirmada" in flow["whatsapp"].sent[1].body

    async with database.session_scope() as session:
        visit = await session.scalar(select(visits.Appointment))
        assert visit is not None
        opportunity = await session.get(Opportunity, visit.opportunity_id)
        action = await session.scalar(
            select(NextAction).where(
                NextAction.status == NextActionStatus.PENDING.value
            )
        )

    # An owner, their calendar, and an obligation to report the result.
    assert visit.status == AppointmentStatus.CONFIRMED.value
    assert visit.advisor_id == built.advisor_id
    assert visit.calendar_id == commercial.ADVISOR_CALENDAR_ID
    assert built.calendar.created == [visit.reference]
    assert opportunity is not None
    assert opportunity.responsible_advisor_id == built.advisor_id
    assert action is not None
    assert action.responsible_member_id == built.advisor_id

    # A commercial question after the handoff goes to the Advisor, not to Maia.
    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.E2E.3",
            body="¿Aceptarían una oferta más baja?",
            from_wa_id=LEAD_WA_ID,
        ),
    )
    await tick(flow, [])
    # The Contact is not left in silence: Product says the approved sentence
    # itself, and Maia composes nothing further.
    assert len(flow["whatsapp"].sent) == 3
    assert "le avisaré al asesor" in flow["whatsapp"].sent[2].body

    async with database.session_scope() as session:
        handoff_row = await session.scalar(select(HumanHandoffRequest))
        snapshot = await ConversationHandling(session).snapshot(visit.conversation_id)
    assert handoff_row is not None
    assert snapshot.mode is HandlingMode.HUMAN
    assert snapshot.holder_member_id == built.advisor_id

    # The Advisor takes it in the CRM and answers on the official channel.
    advisor_auth = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)
    page = await client.get(f"/crm/bandeja/{visit.conversation_id}", auth=advisor_auth)
    assert page.status_code == 200
    taken = await client.post(
        f"/crm/bandeja/{visit.conversation_id}/atender",
        auth=advisor_auth,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    replied = await client.post(
        f"/crm/bandeja/{visit.conversation_id}/responder",
        auth=advisor_auth,
        data={
            "clave": nonce(taken.text),
            "mensaje": "Lo revisamos en la visita, con gusto.",
        },
        follow_redirects=True,
    )
    assert "Se envió el mensaje" in replied.text

    async with database.session_scope() as session:
        human = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.kind == "HumanReply")
        )
        request_row = await session.scalar(select(HumanHandoffRequest))
    assert human is not None
    assert human.body == "Lo revisamos en la visita, con gusto."
    # Taking the conversation is the acknowledgement.
    assert request_row is not None
    assert request_row.status == HandoffStatus.ACKNOWLEDGED.value

    # After the visit, the Advisor records what happened.
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, visit.id)
        assert row is not None
        row.starts_at = visits.now() - visits.timedelta(hours=3)
        row.ends_at = visits.now() - visits.timedelta(hours=1)
        await session.commit()

    agenda = await client.get("/crm/agenda", auth=advisor_auth)
    recorded = await client.post(
        f"/crm/agenda/{visit.id}/resultado",
        auth=advisor_auth,
        data={
            "clave": nonce(agenda.text),
            "asistencia": AppointmentAttendance.ATTENDED.value,
            "notas": "Le gustó; pidió cotización.",
            "accion": "Call",
            "vence": (visits.now() + visits.timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
        },
        follow_redirects=True,
    )
    assert "Se registró el resultado de la visita." in recorded.text

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, visit.id)
        assert row is not None
        actions = list(await session.scalars(select(NextAction)))

    assert row.attendance == AppointmentAttendance.ATTENDED.value
    assert row.attendance_recorded_by == built.advisor_id
    assert row.visit_outcome == "Le gustó; pidió cotización."
    statuses = {action.kind: action.status for action in actions}
    assert statuses["VisitFollowUp"] == NextActionStatus.COMPLETED.value
    assert statuses["Call"] == NextActionStatus.PENDING.value


async def test_a_confirmed_visit_can_be_moved_atomically_by_maia(flow) -> None:
    """Bounded Appointment Logistics: Maia may still move the visit."""
    client = flow["client"]
    database = flow["database"]
    built = flow["built"]

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.MOVE.1", body="Quiero agendar", from_wa_id=LEAD_WA_ID
        ),
    )

    chosen: dict[str, str] = {}

    async def book(tool, prompt):  # noqa: ANN001, ANN202
        slots = await tool("get_available_slots", {"reference": "Casa Roble"})
        # Keep the replacement outside the original 90-minute interval.  The
        # old Calendar event must remain authoritative until the replacement
        # has been secured, so an overlapping candidate is correctly refused.
        chosen["later"] = slots["candidates"][-1]["start"]
        result = await tool(
            "book_appointment",
            {"reference": "Casa Roble", "start": slots["candidates"][0]["start"]},
        )
        assert result["result"] == "confirmed", result
        return "Agendada."

    await tick(flow, [book])

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.MOVE.2",
            body="¿Podemos cambiar la cita?",
            from_wa_id=LEAD_WA_ID,
        ),
    )

    async def move(tool, prompt):  # noqa: ANN001, ANN202
        result = await tool("reschedule_appointment", {"start": chosen["later"]})
        assert result["result"] == "rescheduled", result
        return "Tu visita quedó reagendada."

    await tick(flow, [move])

    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(visits.Appointment).order_by(visits.Appointment.created_at)
            )
        )

    assert len(rows) == 2
    original, replacement = rows
    assert original.status == AppointmentStatus.RESCHEDULED.value
    assert original.rescheduled_to_id == replacement.id
    assert replacement.status == AppointmentStatus.CONFIRMED.value
    assert replacement.advisor_id == built.advisor_id
    # New slot secured before the old one was released.
    assert built.calendar.created == [original.reference, replacement.reference]
    assert built.calendar.deleted == [f"evt-{original.reference}"]


# -- The human-handoff branch --------------------------------------------


async def test_whatsapp_to_human_handoff_to_escalation_and_acknowledgement(
    flow,
) -> None:
    client = flow["client"]
    database = flow["database"]
    built = flow["built"]

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.HAND.1",
            body="Quiero hablar con una persona",
            from_wa_id=LEAD_WA_ID,
        ),
    )

    # Maia is paused, so she composes nothing — but Product still says the
    # approved sentence, because the worst outcome of asking for a person is
    # hearing nothing back.
    await tick(flow, [])
    assert [sent.body for sent in flow["whatsapp"].sent] == [
        "Perfecto, le avisaré al asesor. No puedo confirmar su disponibilidad en "
        "este momento, pero haré todo lo posible para que se comunique contigo "
        "en los próximos minutos."
    ]

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        assert request_row is not None
        conversation_id = request_row.conversation_id
        snapshot = await ConversationHandling(session).snapshot(conversation_id)

    # Nobody is responsible yet, so this is the Administrator's to route.
    assert snapshot.mode is HandlingMode.ADMIN_REVIEW
    assert request_row.advisor_id is None

    # The immediate alert is delivered on the private channel.
    await flow["operations"].tick()
    assert flow["telegram"].sent
    assert "pidió hablar con una persona" in flow["telegram"].sent[0].body

    # Fifteen minutes later, and only once, the Administrator is alerted.
    later = visits.now() + ESCALATION_DELAY + visits.timedelta(minutes=1)
    async with database.session_scope() as session:
        first = await HumanHandoff(session).escalate_due(later)
    async with database.session_scope() as session:
        second = await HumanHandoff(session).escalate_due(later)
    assert (first, second) == (1, 0)

    async with database.session_scope() as session:
        alerts = list(await session.scalars(select(InternalAlert)))
        opportunity = await session.scalar(select(Opportunity))
    escalations = [alert for alert in alerts if alert.kind == "HumanHandoffEscalated"]
    assert len(escalations) == 1
    # And still no automatic reassignment.
    assert opportunity is not None
    assert opportunity.responsible_advisor_id is None

    # The Administrator sees it and hands it to somebody.
    admin_auth = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
    page = await client.get("/crm/alertas", auth=admin_auth)
    assert "Solicitudes de atención humana" in page.text
    assert "Escalada al administrador" in page.text

    taken_page = await client.get(f"/crm/bandeja/{conversation_id}", auth=admin_auth)
    taken = await client.post(
        f"/crm/bandeja/{conversation_id}/atender",
        auth=admin_auth,
        data={"clave": nonce(taken_page.text)},
        follow_redirects=True,
    )
    assert "Ahora tú atiendes esta conversación" in taken.text

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        snapshot = await ConversationHandling(session).snapshot(conversation_id)
    assert request_row is not None
    assert request_row.status == HandoffStatus.ACKNOWLEDGED.value
    assert snapshot.holder_member_id == built.admin_id

    # Returning it to Maia is explicit, and only then may she answer again.
    released = await client.post(
        f"/crm/bandeja/{conversation_id}/liberar",
        auth=admin_auth,
        data={"clave": nonce(taken.text), "modo": HandlingMode.MAIA.value},
        follow_redirects=True,
    )
    assert "Liberaste la conversación." in released.text
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation_id)
    assert snapshot.mode is HandlingMode.MAIA


async def test_maia_can_raise_a_handoff_through_the_typed_tool(flow) -> None:
    client = flow["client"]
    database = flow["database"]

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.TOOL.1",
            body="Tengo una situación complicada con la herencia",
            from_wa_id=LEAD_WA_ID,
        ),
    )

    async def ask_for_a_person(tool, prompt):  # noqa: ANN001, ANN202
        result = await tool(
            "request_human_handoff", {"reason": "Tema legal fuera de mi alcance"}
        )
        assert result["result"] == "requested", result
        # The acknowledgement is Product's copy, not the Model's.
        assert "No puedo confirmar su disponibilidad" in result["acknowledgement"]
        return result["acknowledgement"]

    await tick(flow, [ask_for_a_person])

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        assert request_row is not None
        snapshot = await ConversationHandling(session).snapshot(
            request_row.conversation_id
        )

    assert request_row.status == HandoffStatus.PENDING.value
    assert not snapshot.maia_may_reply
    # The warm acknowledgement itself did go out: it answers what they wrote.
    assert len(flow["whatsapp"].sent) == 1
    assert "le avisaré al asesor" in flow["whatsapp"].sent[0].body


# -- Availability without an authoritative calendar ----------------------


async def test_maia_offers_no_times_when_no_calendar_is_authoritative(flow) -> None:
    """Fail closed, and say so honestly rather than inventing availability."""
    client = flow["client"]
    database = flow["database"]
    built = flow["built"]

    async with database.session_scope() as session:
        member = await session.get(visits.OrganizationMember, built.advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

    await post_webhook(
        client,
        webhooks.text_message(
            wamid="wamid.NOCAL.1", body="Quiero agendar", from_wa_id=LEAD_WA_ID
        ),
    )

    async def try_to_book(tool, prompt):  # noqa: ANN001, ANN202
        slots = await tool("get_available_slots", {"reference": "Casa Roble"})
        assert slots["result"] == "temporarily_unavailable", slots
        assert slots["detail"] == "NoAuthoritativeCalendar"
        return "Ahora no puedo consultar horarios; te confirmo en un momento."

    await tick(flow, [try_to_book])

    async with database.session_scope() as session:
        assert list(await session.scalars(select(visits.Appointment))) == []
