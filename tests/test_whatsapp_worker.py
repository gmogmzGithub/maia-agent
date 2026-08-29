"""End-to-end worker behaviour with Hermes and Meta stubbed.

This is where Checkpoint 2's exit condition is asserted as far as it can be
without the live channel: every inbound message survives, the group produces
exactly one coherent reply covering all of them, and a duplicate webhook
produces neither duplicate processing nor a duplicate reply.

Hermes and Meta are stubbed *only* here. Their real contracts are exercised
elsewhere: the JSON-RPC surface in `test_hermes_client.py`, Meta's signature in
`test_whatsapp_signature.py`, and the live channel in the checkpoint run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import delete, select

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.engine import Database
from realestate.db.models import (
    AgentSession,
    Conversation,
    InboxGroup,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.copy import SPANISH_DAYS
from realestate.domain.inbox import MAX_ATTEMPTS, InboxService
from realestate.domain.outbox import PROCESSING_FAILURE_BODY
from realestate.hermes.sessions import TurnResult
from realestate.worker import whatsapp as worker_module
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, age_pending_inbox, requires_postgres
from tests.fixtures import webhooks
from tests.fixtures.stubs import SCHEDULE, StubWhatsApp

pytestmark = requires_postgres


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await session.execute(delete(OutboxMessage))
        await session.execute(delete(InboxMessage))
        await session.execute(delete(InboxGroup))
        await session.execute(delete(AgentSession))
        await session.execute(delete(Conversation))
        await session.execute(delete(LeadEngagementCycle))
        await session.execute(delete(Lead))
        await session.commit()
    yield db
    await db.dispose()


@pytest.fixture
def stub_hermes(monkeypatch: pytest.MonkeyPatch):
    """Stub only the Hermes turn.

    ``session_for_cycle`` and ``bind_cycle_session`` are pure database
    functions now, so the real ones run — which means these tests also cover
    the binding lifecycle rather than mocking it away.
    """
    state: dict = {"prompts": [], "reply": "Claro, con gusto te ayudo.", "raises": None}

    async def fake_run_turn(client, session, text, **kwargs):
        state["prompts"].append(text)
        if state["raises"] is not None:
            raise state["raises"]

        # Mirror _attach: a cycle's first turn has no durable session yet, so
        # one is created and published through on_attached before prompting.
        durable = session.hermes_session_id
        if not durable:
            state["created"] = state.get("created", 0) + 1
            durable = f"durable-{state['created']}"
            if on_attached := kwargs.get("on_attached"):
                await on_attached(durable)

        if during := state.get("during_turn"):
            await during()
        on_poll = kwargs.get("on_poll")
        on_adopted = kwargs.get("on_adopted")
        injected: list[str] = []
        if on_poll is not None and state.get("poll_once"):
            late = await on_poll()
            if late:
                injected.append(late)
                if on_adopted is not None:
                    await on_adopted()
        return TurnResult(
            text=state["reply"],
            tools_used=[],
            injected=injected,
            hermes_session_id=durable,
        )

    monkeypatch.setattr(worker_module, "run_turn", fake_run_turn)
    return state


def lead_words(prompts: list[str]) -> list[str]:
    """Each prompt minus the product's leading date-context line.

    Asserted separately in `test_the_prompt_carries_todays_date`; here what
    matters is that the Lead's own words arrive whole and grouped.
    """
    stripped = []
    for prompt in prompts:
        first, _, rest = prompt.partition("\n")
        assert first.startswith("[Contexto del producto"), first
        stripped.append(rest)
    return stripped


def build_worker(database, whatsapp) -> WhatsAppWorker:
    return WhatsAppWorker(
        database=database,
        hermes=object(),  # never used: the session/turn contracts are stubbed
        whatsapp=whatsapp,
        sales_profile="sales",
        schedule=SCHEDULE,
        max_concurrent=3,
    )


def inbound(wamid: str, body: str, *, seconds_ago: int = 0, from_wa_id: str | None = None):
    payload = webhooks.text_message(
        wamid=wamid,
        body=body,
        timestamp=int(datetime.now(tz=UTC).timestamp()) - seconds_ago,
        **({"from_wa_id": from_wa_id} if from_wa_id else {}),
    )
    return parse_webhook(payload).messages[0]


async def accept(database, *messages) -> None:
    async with database.session_scope() as session:
        service = InboxService(session)
        for message in messages:
            await service.accept(message)
    await age_pending_inbox(database)


async def rows(database, model) -> list:
    async with database.session_scope() as session:
        return list((await session.execute(select(model))).scalars().all())


# --- The happy path ----------------------------------------------------------


async def test_one_message_produces_one_delivered_reply(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola, informes de Casa Roble"))

    await build_worker(database, whatsapp).tick()

    assert len(whatsapp.sent) == 1
    assert whatsapp.sent[0].to_wa_id == webhooks.LEAD_WA_ID
    assert whatsapp.sent[0].body == stub_hermes["reply"]

    outbox = await rows(database, OutboxMessage)
    assert len(outbox) == 1
    assert outbox[0].status == OutboxStatus.SENT.value
    assert outbox[0].provider_message_id == "wamid.1"


async def test_model_markdown_is_converted_before_the_whatsapp_send(
    database, stub_hermes
) -> None:
    """Regression for the real catalog reply that showed leftover asterisks."""
    stub_hermes["reply"] = (
        "¡Claro! Tenemos **4 opciones disponibles en venta**:\n\n"
        "🏠 **Casas:**\n\n"
        "1. **Casa Roble** - $3,000,000 MXN\n"
        "_Consulta disponibilidad_"
    )
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w-format", "qué propiedades tienen disponibles?"))

    await build_worker(database, whatsapp).tick()

    assert whatsapp.sent[0].body == (
        "¡Claro! Tenemos *4 opciones disponibles en venta*:\n\n"
        "🏠 *Casas:*\n\n"
        "1. *Casa Roble* - $3,000,000 MXN\n"
        "_Consulta disponibilidad_"
    )
    assert "**" not in whatsapp.sent[0].body


async def test_rapid_fragments_produce_one_coherent_reply(database, stub_hermes) -> None:
    whatsapp = StubWhatsApp()
    await accept(
        database,
        inbound("w1", "hola", seconds_ago=3),
        inbound("w2", "me interesa Casa Roble", seconds_ago=2),
        inbound("w3", "cuánto cuesta?", seconds_ago=1),
    )

    await build_worker(database, whatsapp).tick()

    # One turn covering all three, one reply.
    # One prompt covering all three, under the product's date line.
    assert lead_words(stub_hermes["prompts"]) == [
        "hola\nme interesa Casa Roble\ncuánto cuesta?"
    ]
    assert len(whatsapp.sent) == 1

    outbox = await rows(database, OutboxMessage)
    inbox = await rows(database, InboxMessage)
    assert len(outbox[0].covered_inbox_ids) == 3
    assert {str(m.id) for m in inbox} == set(outbox[0].covered_inbox_ids)
    assert all(m.status == InboxStatus.PROCESSED.value for m in inbox)


async def test_the_prompt_carries_todays_date(database, stub_hermes) -> None:
    """The Model has no clock, and a guessed date reads as "no availability".

    A rehearsal produced exactly that: «necesito saber cuál es el próximo
    domingo», a guessed date, an empty candidate list, and the Agent telling the
    Lead there was nothing available while the calendar was completely free.
    """
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "quiero ir el viernes por la tarde"))

    await build_worker(database, whatsapp).tick()

    today = datetime.now(tz=SCHEDULE.zone).date()
    line = stub_hermes["prompts"][0].splitlines()[0]
    assert today.isoformat() in line
    # Named in Spanish, and named as product context rather than as the Lead
    # speaking, so the Model neither answers it nor quotes it back.
    assert SPANISH_DAYS[today.weekday()] in line
    assert line.startswith("[Contexto del producto")
    # The Lead's words are untouched below it.
    assert stub_hermes["prompts"][0].endswith("quiero ir el viernes por la tarde")


async def test_every_inbound_message_survives_as_its_own_record(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(
        database,
        inbound("w1", "uno", seconds_ago=3),
        inbound("w2", "dos", seconds_ago=2),
    )

    await build_worker(database, whatsapp).tick()

    inbox = await rows(database, InboxMessage)
    assert {m.wamid for m in inbox} == {"w1", "w2"}


# --- Idempotency -------------------------------------------------------------


async def test_a_duplicate_webhook_produces_no_duplicate_reply(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    message = inbound("w-dup", "hola")
    await accept(database, message)

    await build_worker(database, whatsapp).tick()
    # Meta redelivers the same message after it was already processed.
    await accept(database, message)
    await build_worker(database, whatsapp).tick()

    assert len(whatsapp.sent) == 1
    assert len(await rows(database, OutboxMessage)) == 1
    assert len(await rows(database, InboxMessage)) == 1


async def test_a_repeated_tick_does_not_resend(database, stub_hermes) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola"))
    worker = build_worker(database, whatsapp)

    await worker.tick()
    await worker.tick()
    await worker.tick()

    assert len(whatsapp.sent) == 1


# --- In-flight reconciliation ------------------------------------------------


def arriving(database, wamid: str, body: str):
    """A callback that persists a new inbound message mid-turn."""

    async def _arrive() -> None:
        async with database.session_scope() as session:
            await InboxService(session).accept(inbound(wamid, body))

    return _arrive


async def test_a_fragment_arriving_mid_turn_is_folded_into_it(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola"))
    stub_hermes["during_turn"] = arriving(database, "w2", "perdón, de Casa Roble")
    stub_hermes["poll_once"] = True

    await build_worker(database, whatsapp).tick()

    outbox = await rows(database, OutboxMessage)
    inbox = await rows(database, InboxMessage)
    # The first turn saw only "hola"; the correction was injected into it.
    assert lead_words(stub_hermes["prompts"]) == ["hola"]
    # One reply, covering both messages.
    assert len(whatsapp.sent) == 1
    assert len(outbox[0].covered_inbox_ids) == 2
    assert all(m.status == InboxStatus.PROCESSED.value for m in inbox)


async def test_an_unadopted_message_withholds_the_draft(database, stub_hermes) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola"))
    # The fragment lands mid-turn, but Hermes never takes it in.
    stub_hermes["during_turn"] = arriving(database, "w2", "espera, mejor otra cosa")
    stub_hermes["poll_once"] = False

    await build_worker(database, whatsapp).tick()

    # The draft was withheld rather than sent while ignoring part of the Lead.
    assert whatsapp.sent == []
    assert await rows(database, OutboxMessage) == []
    inbox = await rows(database, InboxMessage)
    assert all(m.status == InboxStatus.PENDING.value for m in inbox)


async def test_a_withheld_draft_is_answered_together_on_the_next_cycle(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola"))
    stub_hermes["during_turn"] = arriving(database, "w2", "espera, mejor otra cosa")
    worker = build_worker(database, whatsapp)

    await worker.tick()  # withheld
    stub_hermes["during_turn"] = None
    await age_pending_inbox(database)
    await worker.tick()  # both together

    assert lead_words(stub_hermes["prompts"])[-1] == "hola\nespera, mejor otra cosa"
    assert len(whatsapp.sent) == 1
    outbox = await rows(database, OutboxMessage)
    assert len(outbox) == 1
    assert len(outbox[0].covered_inbox_ids) == 2


# --- Failure handling --------------------------------------------------------


async def test_a_failing_turn_retries_and_then_speaks_honestly(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(database, inbound("w1", "hola"))
    stub_hermes["raises"] = RuntimeError("model provider unavailable")
    worker = build_worker(database, whatsapp)

    for _ in range(MAX_ATTEMPTS):
        await age_pending_inbox(database)
        await worker.tick()

    inbox = await rows(database, InboxMessage)
    outbox = await rows(database, OutboxMessage)

    # The inbound message is kept, not deleted, and not marked successful.
    assert inbox[0].status == InboxStatus.FAILED.value
    assert inbox[0].attempts == MAX_ATTEMPTS
    # Exactly one deterministic contingency message, not a model-authored one.
    assert len(outbox) == 1
    assert outbox[0].body == PROCESSING_FAILURE_BODY
    assert outbox[0].kind == "ProcessingFailureNotice"
    assert len(whatsapp.sent) == 1


async def test_an_ambiguous_send_is_not_resent_on_the_next_tick(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp(SendResult(SendOutcome.UNKNOWN, detail="read timeout"))
    await accept(database, inbound("w1", "hola"))
    worker = build_worker(database, whatsapp)

    await worker.tick()
    await worker.tick()

    assert len(whatsapp.sent) == 1
    outbox = await rows(database, OutboxMessage)
    assert outbox[0].status == OutboxStatus.DELIVERY_UNKNOWN.value


# --- Engagement cycles --------------------------------------------------------


async def test_one_hermes_session_serves_the_whole_cycle(database, stub_hermes) -> None:
    whatsapp = StubWhatsApp()
    worker = build_worker(database, whatsapp)

    await accept(database, inbound("w1", "hola"))
    await worker.tick()
    await accept(database, inbound("w2", "otra pregunta"))
    await worker.tick()

    sessions = await rows(database, AgentSession)
    assert len(sessions) == 1
    assert len(whatsapp.sent) == 2


async def test_a_returning_lead_after_expiry_gets_a_new_cycle_and_session(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    worker = build_worker(database, whatsapp)
    await accept(database, inbound("w1", "hola"))
    await worker.tick()

    # The cycle expires.
    async with database.session_scope() as session:
        cycle = (await session.execute(select(LeadEngagementCycle))).scalar_one()
        cycle.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()

    await accept(database, inbound("w2", "hola de nuevo"))
    await worker.tick()

    cycles = await rows(database, LeadEngagementCycle)
    sessions = await rows(database, AgentSession)
    leads = await rows(database, Lead)

    # A new cycle and a new session against the same stable Lead (ADR-0012).
    assert len(leads) == 1
    assert len(cycles) == 2
    assert len(sessions) == 2
    assert {s.cycle_id for s in sessions} == {c.id for c in cycles}


# --- Concurrency --------------------------------------------------------------


async def test_separate_conversations_are_processed_in_one_tick(
    database, stub_hermes
) -> None:
    whatsapp = StubWhatsApp()
    await accept(
        database,
        inbound("w1", "hola"),
        inbound("w2", "hola", from_wa_id="5213311112222"),
        inbound("w3", "hola", from_wa_id="5213344445555"),
    )

    await build_worker(database, whatsapp).tick()

    assert len(whatsapp.sent) == 3
    assert len(await rows(database, Conversation)) == 3


async def test_the_concurrency_limit_is_respected(database, stub_hermes) -> None:
    whatsapp = StubWhatsApp()
    await accept(
        database,
        inbound("w1", "hola"),
        inbound("w2", "hola", from_wa_id="5213311112222"),
        inbound("w3", "hola", from_wa_id="5213344445555"),
        inbound("w4", "hola", from_wa_id="5213366667777"),
    )
    worker = WhatsAppWorker(
        database=database,
        hermes=object(),
        whatsapp=whatsapp,
        sales_profile="sales",
        schedule=SCHEDULE,
        max_concurrent=2,
    )

    await worker.tick()

    # Excess Lead work stays durably queued rather than running (P-037).
    assert len(whatsapp.sent) == 2
    pending = [
        m for m in await rows(database, InboxMessage)
        if m.status == InboxStatus.PENDING.value
    ]
    assert len(pending) == 2


# --- Recovery, empty drafts, and the deterministic confirmation ---------------


async def test_a_crashed_workers_lease_is_recovered_and_reported(
    database, stub_hermes, caplog: pytest.LogCaptureFixture
) -> None:
    """P-038: an expired lease returns the work rather than stranding it."""
    import logging

    await accept(database, inbound("w-recover", "hola"))
    async with database.session_scope() as session:
        group = await InboxService(session).claim(
            (await session.execute(select(Conversation))).scalar_one().id
        )
        assert group is not None
    async with database.session_scope() as session:
        row = await session.get(InboxGroup, group.group_id)
        row.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()

    worker = build_worker(database, StubWhatsApp())
    with caplog.at_level(logging.WARNING, logger="realestate.worker.whatsapp"):
        await worker.tick()

    assert "expired lease" in caplog.text
    # The work is back in the queue with its attempt consumed, waiting out the
    # P-035 backoff rather than being retried inside the same tick.
    messages = await rows(database, InboxMessage)
    assert [m.status for m in messages] == [InboxStatus.PENDING.value]
    assert messages[0].attempts == 1


async def test_a_conversation_another_worker_already_claimed_is_left_alone(
    database, stub_hermes
) -> None:
    """The database enforces the lane; the worker simply steps aside."""
    await accept(database, inbound("w-claimed", "hola"))
    async with database.session_scope() as session:
        conversation_id = (await session.execute(select(Conversation))).scalar_one().id
        assert await InboxService(session).claim(conversation_id) is not None

    worker = build_worker(database, StubWhatsApp())
    await worker._process_one(conversation_id)

    assert await rows(database, OutboxMessage) == []


async def test_nothing_claimable_is_a_quiet_tick(database, stub_hermes) -> None:
    worker = build_worker(database, StubWhatsApp())

    await worker.tick()

    assert stub_hermes["prompts"] == []


async def test_an_empty_draft_is_withheld_rather_than_sent(
    database, stub_hermes, caplog: pytest.LogCaptureFixture
) -> None:
    """A blank WhatsApp message is worse than a retry."""
    import logging

    stub_hermes["reply"] = "   "
    await accept(database, inbound("w-empty-draft", "hola"))
    worker = build_worker(database, StubWhatsApp())

    with caplog.at_level(logging.WARNING, logger="realestate.worker.whatsapp"):
        await worker.tick()

    assert "empty draft" in caplog.text
    assert await rows(database, OutboxMessage) == []
    assert [m.status for m in await rows(database, InboxMessage)] == [
        InboxStatus.PENDING.value
    ]


async def test_a_pending_message_with_no_text_offers_nothing_to_the_turn(
    database, stub_hermes
) -> None:
    """A media message has no words to fold in; the turn must not be handed an
    empty string as though the Lead had said something."""
    await accept(database, inbound("w-media-1", "hola"))
    stub_hermes["poll_once"] = True

    async def a_textless_message_arrives() -> None:
        async with database.session_scope() as session:
            row = (
                await session.execute(
                    select(InboxMessage).where(InboxMessage.wamid == "w-media-1")
                )
            ).scalar_one()
            session.add(
                InboxMessage(
                    wamid="w-media-2",
                    organization_id=row.organization_id,
                    conversation_id=row.conversation_id,
                    lead_id=row.lead_id,
                    cycle_id=row.cycle_id,
                    from_wa_id=row.from_wa_id,
                    message_type="image",
                    text=None,
                    sent_at=datetime.now(tz=UTC),
                    raw_message={},
                    status=InboxStatus.PENDING.value,
                )
            )
            await session.commit()

    stub_hermes["during_turn"] = a_textless_message_arrives
    worker = build_worker(database, StubWhatsApp())

    await worker.tick()

    # Nothing was injected, so the draft is withheld and the pair is answered
    # together on the next cycle rather than half-answered now.
    assert await rows(database, OutboxMessage) == []


async def test_a_lease_lost_during_the_turn_leaves_the_outbox_row_standing(
    database, stub_hermes, caplog: pytest.LogCaptureFixture
) -> None:
    """The Outbox row is keyed on the group, so the recovered attempt cannot add
    a second reply — but the loss is reported."""
    import logging

    await accept(database, inbound("w-lease-lost", "hola"))

    async def recovery_reassigns_the_group() -> None:
        async with database.session_scope() as session:
            for row in (await session.execute(select(InboxGroup))).scalars():
                row.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
            await session.commit()
        async with database.session_scope() as session:
            await InboxService(session).recover_expired_claims()
        await age_pending_inbox(database)
        # A second worker picks the recovered work up, so nothing is left
        # Pending — this worker's *only* problem is that its lease is gone.
        async with database.session_scope() as session:
            conversation_id = (
                await session.execute(select(Conversation))
            ).scalar_one().id
            assert await InboxService(session).claim(conversation_id) is not None

    stub_hermes["during_turn"] = recovery_reassigns_the_group
    worker = build_worker(database, StubWhatsApp())

    with caplog.at_level(logging.WARNING, logger="realestate.worker.whatsapp"):
        await worker.tick()

    assert "Lost the lease" in caplog.text
    assert len(await rows(database, OutboxMessage)) == 1


async def test_polling_with_nothing_pending_offers_no_text(database, stub_hermes) -> None:
    """The ordinary case inside the reconciliation window: the Lead said nothing
    more, so there is nothing to fold in and the draft stands."""
    await accept(database, inbound("w-quiet", "hola"))
    stub_hermes["poll_once"] = True
    whatsapp = StubWhatsApp()

    await build_worker(database, whatsapp).tick()

    assert [record.body for record in whatsapp.sent] == [stub_hermes["reply"]]
    assert len(await rows(database, OutboxMessage)) == 1


# --- The deterministic appointment notice replaces the draft (P-042, P-044) ---


async def test_a_pending_confirmation_replaces_the_models_draft(
    database, stub_hermes, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """What the Lead is told about an Appointment is rendered from the persisted
    row, never from the Model's account of the booking."""
    import logging
    import uuid as uuid_module

    from realestate.domain.appointments import LEAD_NOTICE_CONFIRMATION, LeadNotice

    stub_hermes["reply"] = "¡Listo! Te veo el jueves, creo."
    notice = LeadNotice(
        appointment_id=uuid_module.uuid4(),
        reference="APT-123",
        kind=LEAD_NOTICE_CONFIRMATION,
        body="Tu visita quedó agendada para el jueves 13/08/2026 a las 16:00.",
    )
    notified: list[uuid_module.UUID] = []

    async def owed(session, conversation, schedule):  # noqa: ANN001, ANN202
        return notice

    async def record(session, appointment_id):  # noqa: ANN001, ANN202
        notified.append(appointment_id)

    monkeypatch.setattr(worker_module, "pending_lead_notice", owed)
    monkeypatch.setattr(worker_module, "mark_lead_notified", record)

    await accept(database, inbound("w-notice", "el jueves"))
    whatsapp = StubWhatsApp()
    worker = build_worker(database, whatsapp)

    with caplog.at_level(logging.INFO, logger="realestate.worker.whatsapp"):
        await worker.tick()

    assert [record.body for record in whatsapp.sent] == [notice.body]
    assert "creo" not in whatsapp.sent[0].body
    assert "the Model's draft is discarded" in caplog.text
    # Persisted immediately, or the next turn would release it again under a
    # different group key.
    assert notified == [notice.appointment_id]
    assert [row.kind for row in await rows(database, OutboxMessage)] == [notice.kind]


async def test_an_empty_draft_still_releases_an_owed_confirmation(
    database, stub_hermes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The notice does not depend on the Model producing anything usable."""
    import uuid as uuid_module

    from realestate.domain.appointments import LEAD_NOTICE_CONFIRMATION, LeadNotice

    stub_hermes["reply"] = "  "
    notice = LeadNotice(
        appointment_id=uuid_module.uuid4(),
        reference="APT-124",
        kind=LEAD_NOTICE_CONFIRMATION,
        body="Tu visita quedó agendada.",
    )

    async def owed(session, conversation, schedule):  # noqa: ANN001, ANN202
        return notice

    async def record(session, appointment_id):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(worker_module, "pending_lead_notice", owed)
    monkeypatch.setattr(worker_module, "mark_lead_notified", record)

    await accept(database, inbound("w-notice-empty", "el jueves"))
    whatsapp = StubWhatsApp()

    await build_worker(database, whatsapp).tick()

    assert [record.body for record in whatsapp.sent] == [notice.body]


async def test_a_reworded_approved_message_is_restored_before_release(
    database, stub_hermes, caplog
) -> None:
    """Canonicalisation runs on the released body, not just in the domain."""
    import logging

    from realestate.domain.copy import PROPERTY_CLARIFICATION

    stub_hermes["reply"] = (
        "No estoy seguro de cual propiedad estas buscando, me puedes decir mas detalles?"
    )
    await accept(database, inbound("w-canon", "cuánto cuesta?"))
    whatsapp = StubWhatsApp()

    with caplog.at_level(logging.INFO, logger="realestate.worker.whatsapp"):
        await build_worker(database, whatsapp).tick()

    assert [record.body for record in whatsapp.sent] == [PROPERTY_CLARIFICATION]
    assert "Restored approved copy" in caplog.text
