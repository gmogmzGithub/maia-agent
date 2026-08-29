"""The Administrative Channel worker (P-040, ADR-0001).

Only allowlisted Telegram identities may reach the Administrative Role, an
unauthorised attempt is still recorded, and a re-polled update never executes
twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from realestate.channels.telegram.client import TelegramUpdate, parse_updates
from realestate.db.engine import Database
from realestate.db.models import AdminMessage, AgentRole, AgentSession, ChannelCursor
from realestate.hermes.sessions import TurnResult
from realestate.worker import telegram as worker_module
from realestate.worker.telegram import TelegramAdminWorker
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres

BROKER = "111111"
DEVELOPER = "222222"
STRANGER = "999999"
CHAT = "555000"


class StubTelegram:
    """Serves a scripted batch of updates and records what was sent back."""

    def __init__(self, updates: list[TelegramUpdate]) -> None:
        self._updates = updates
        self.sent: list[tuple[str, str]] = []
        self.offsets: list[int] = []
        self.configured = True
        # Stage 9: the worker resolves which Organization's administrative
        # channel this bot serves from a channel binding on its id, and does
        # nothing at all when the bot is unbound (ADR-0050).
        self.bot_id = commercial.TEST_TELEGRAM_BOT_ID

    async def get_updates(self, offset: int, limit: int = 20) -> list[TelegramUpdate]:
        self.offsets.append(offset)
        pending = [u for u in self._updates if u.update_id >= offset]
        return pending

    async def send_message(self, chat_id: str, text: str) -> bool:
        self.sent.append((chat_id, text))
        return True


def update(update_id: int, text: str, *, user: str = BROKER) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        chat_id=CHAT,
        from_user_id=user,
        from_username="gmo",
        text=text,
        sent_at=datetime.now(tz=UTC),
        raw={"update_id": update_id, "message": {"text": text}},
    )


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await session.execute(delete(AdminMessage))
        await session.execute(delete(ChannelCursor))
        await session.execute(delete(AgentSession))
        await session.commit()
    yield db
    await db.dispose()


@pytest.fixture
def stub_turn(monkeypatch: pytest.MonkeyPatch):
    state: dict = {"prompts": [], "reply": "Listo, Casa Roble quedó inactiva."}

    async def fake_run_turn(client, session, text, **kwargs):
        state["prompts"].append(text)
        durable = session.hermes_session_id
        if not durable:
            state["created"] = state.get("created", 0) + 1
            durable = f"admin-durable-{state['created']}"
            if on_attached := kwargs.get("on_attached"):
                await on_attached(durable)
        return TurnResult(text=state["reply"], hermes_session_id=durable)

    monkeypatch.setattr(worker_module, "run_turn", fake_run_turn)
    return state


def build(database, telegram, allowed=(BROKER, DEVELOPER)) -> TelegramAdminWorker:
    return TelegramAdminWorker(
        database=database,
        hermes=object(),
        telegram=telegram,
        admin_profile="admin",
        allowed_user_ids=frozenset(allowed),
    )


async def rows(database, model) -> list:
    async with database.session_scope() as session:
        return list((await session.execute(select(model))).scalars().all())


# --- Allowlist ----------------------------------------------------------------


async def test_an_allowlisted_administrator_is_served(database, stub_turn) -> None:
    telegram = StubTelegram([update(1, "desactiva Casa Roble")])

    await build(database, telegram).tick()

    assert stub_turn["prompts"] == ["desactiva Casa Roble"]
    assert telegram.sent == [(CHAT, stub_turn["reply"])]


async def test_both_administrators_have_the_same_authority(database, stub_turn) -> None:
    # P-040: Broker and Developer are equal during Stage 0.
    telegram = StubTelegram(
        [update(1, "desactiva Casa Roble", user=BROKER),
         update(2, "actívala de nuevo", user=DEVELOPER)]
    )

    await build(database, telegram).tick()

    assert len(telegram.sent) == 2


async def test_a_stranger_reaches_no_session_and_gets_no_reply(
    database, stub_turn
) -> None:
    telegram = StubTelegram([update(1, "desactiva Casa Roble", user=STRANGER)])

    await build(database, telegram).tick()

    assert stub_turn["prompts"] == []
    assert telegram.sent == []
    assert await rows(database, AgentSession) == []


async def test_an_unauthorised_attempt_is_still_recorded(database, stub_turn) -> None:
    telegram = StubTelegram([update(1, "desactiva Casa Roble", user=STRANGER)])

    await build(database, telegram).tick()

    messages = await rows(database, AdminMessage)
    assert len(messages) == 1
    assert messages[0].authorized is False
    assert messages[0].from_user_id == STRANGER
    assert messages[0].processed_at is None


async def test_an_empty_allowlist_serves_nobody(database, stub_turn) -> None:
    telegram = StubTelegram([update(1, "desactiva Casa Roble")])

    await build(database, telegram, allowed=()).tick()

    assert telegram.sent == []
    assert await rows(database, AdminMessage) == []


# --- Durability and idempotency -------------------------------------------------


async def test_every_message_is_persisted(database, stub_turn) -> None:
    telegram = StubTelegram([update(1, "hola"), update(2, "lista las propiedades")])

    await build(database, telegram).tick()

    messages = await rows(database, AdminMessage)
    assert {m.update_id for m in messages} == {1, 2}
    assert all(m.authorized and m.processed_at is not None for m in messages)


async def test_a_repolled_update_is_not_executed_twice(database, stub_turn) -> None:
    telegram = StubTelegram([update(1, "desactiva Casa Roble")])
    worker = build(database, telegram)

    await worker.tick()
    # Telegram re-delivers the same update before the cursor took effect.
    telegram.offsets.clear()
    async with database.session_scope() as session:
        organization_id = await commercial.organization_id(session)
    await worker._handle(update(1, "desactiva Casa Roble"), organization_id)

    assert len(stub_turn["prompts"]) == 1
    assert len(telegram.sent) == 1
    assert len(await rows(database, AdminMessage)) == 1


async def test_the_cursor_advances_past_processed_updates(database, stub_turn) -> None:
    telegram = StubTelegram([update(7, "hola"), update(8, "adiós")])
    worker = build(database, telegram)

    await worker.tick()
    await worker.tick()

    # The second poll asks for everything after the highest update seen.
    assert telegram.offsets == [0, 9]


async def test_a_restart_resumes_rather_than_replaying(database, stub_turn) -> None:
    telegram = StubTelegram([update(5, "hola")])
    await build(database, telegram).tick()

    # A brand-new worker instance, as after a process restart.
    fresh = StubTelegram([])
    await build(database, fresh).tick()

    assert fresh.offsets == [6]


# --- Sessions -------------------------------------------------------------------


async def test_one_persistent_session_per_administrator_chat(
    database, stub_turn
) -> None:
    telegram = StubTelegram([update(1, "hola"), update(2, "otra cosa")])

    await build(database, telegram).tick()

    sessions = await rows(database, AgentSession)
    assert len(sessions) == 1
    assert sessions[0].role == AgentRole.ADMINISTRATIVE.value
    assert sessions[0].channel_key == f"telegram:{CHAT}"


async def test_the_administrative_session_is_bound_before_the_turn(
    database, stub_turn
) -> None:
    # The Backend resolves administrative authority from this binding, so a tool
    # call in the model's first step would be refused if it landed afterwards.
    telegram = StubTelegram([update(1, "desactiva Casa Roble")])

    await build(database, telegram).tick()

    sessions = await rows(database, AgentSession)
    assert sessions[0].hermes_session_id == "admin-durable-1"


async def test_a_failing_turn_does_not_wedge_the_channel(database, monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("model provider down")

    monkeypatch.setattr(worker_module, "run_turn", boom)
    telegram = StubTelegram([update(1, "desactiva Casa Roble")])
    worker = build(database, telegram)

    await worker.tick()

    # The message is recorded, nothing was sent, and the cursor still moved on
    # so the next administrative message is not blocked behind this one.
    messages = await rows(database, AdminMessage)
    assert len(messages) == 1
    assert messages[0].processed_at is None
    assert telegram.sent == []
    async with database.session_scope() as session:
        # The cursor is keyed by (Organization, channel) since Stage 9: two
        # Organizations polling their own bots share a channel *name* and
        # nothing else (ADR-0050).
        cursor = await session.get(
            ChannelCursor, (await commercial.organization_id(session), "telegram")
        )
    assert cursor.cursor == 2


# --- Payload parsing --------------------------------------------------------------


def test_a_plain_text_message_is_parsed() -> None:
    payload = {
        "ok": True,
        "result": [
            {
                "update_id": 42,
                "message": {
                    "message_id": 7,
                    "date": 1770000000,
                    "chat": {"id": 555, "type": "private"},
                    "from": {"id": 111, "username": "gmo"},
                    "text": "desactiva Casa Roble",
                },
            }
        ],
    }

    updates = parse_updates(payload)

    assert len(updates) == 1
    assert updates[0].update_id == 42
    assert updates[0].chat_id == "555"
    assert updates[0].from_user_id == "111"
    assert updates[0].text == "desactiva Casa Roble"


@pytest.mark.parametrize(
    "item",
    [
        {"update_id": 1, "edited_message": {"text": "x"}},
        {"update_id": 2, "channel_post": {"text": "x"}},
        {"update_id": 3, "callback_query": {"data": "x"}},
        {"update_id": 4, "message": {"chat": {"id": 1}}},  # no sender
        {"update_id": 5},
    ],
)
def test_non_conversational_updates_are_ignored(item: dict) -> None:
    assert parse_updates({"result": [item]}) == []


def test_an_empty_response_is_not_an_error() -> None:
    assert parse_updates({"ok": True, "result": []}) == []


# --- Messages that reach no model turn ----------------------------------------


async def test_an_authorised_message_with_no_text_is_recorded_but_not_answered(
    database, stub_turn
) -> None:
    """A photo or a sticker is an attempt worth recording, not a command."""
    telegram = StubTelegram([update(1, text=None)])
    worker = build(database, telegram)

    await worker.tick()

    assert stub_turn["prompts"] == []
    assert telegram.sent == []
    # Still persisted: an audit trail records attempts, not just commands.
    assert [m.update_id for m in await rows(database, AdminMessage)] == [1]


async def test_a_whitespace_only_message_is_not_a_command(database, stub_turn) -> None:
    telegram = StubTelegram([update(2, text="   ")])

    await build(database, telegram).tick()

    assert stub_turn["prompts"] == []
    assert telegram.sent == []


async def test_a_rejected_telegram_reply_is_reported(
    database, stub_turn, caplog
) -> None:
    """Otherwise a rejected send looks identical to a delivered one: the message
    is marked processed either way."""
    import logging

    class RejectingTelegram(StubTelegram):
        async def send_message(self, chat_id: str, text: str) -> bool:
            await super().send_message(chat_id, text)
            return False

    telegram = RejectingTelegram([update(3, text="lista las propiedades")])

    with caplog.at_level(logging.ERROR, logger="realestate.worker.telegram"):
        await build(database, telegram).tick()

    assert "Telegram rejected the reply" in caplog.text
    assert len(telegram.sent) == 1


async def test_the_tools_an_administrative_turn_used_are_logged(
    database, stub_turn, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Which tools a mutation went through is the first thing an operator needs
    when reconciling an administrative change."""
    import logging

    async def turn_using_a_tool(client, session, text, **kwargs):  # noqa: ANN001, ANN202
        durable = session.hermes_session_id or "admin-durable-1"
        if not session.hermes_session_id and (on_attached := kwargs.get("on_attached")):
            await on_attached(durable)
        return TurnResult(
            text="Listo.",
            tools_used=["set_property_status"],
            hermes_session_id=durable,
        )

    monkeypatch.setattr(worker_module, "run_turn", turn_using_a_tool)
    telegram = StubTelegram([update(4, text="desactiva Casa Roble")])

    with caplog.at_level(logging.INFO, logger="realestate.worker.telegram"):
        await build(database, telegram).tick()

    assert "set_property_status" in caplog.text
