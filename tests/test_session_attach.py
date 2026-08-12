"""Session attach: the durable id is the truth, the gateway handle is not.

Found the hard way during the first live runs. ``session.create`` returns two
identifiers:

* ``stored_session_id`` — durable, and the value Hermes hands plugin tool
  handlers as ``session_id``, so it is what the Role binding is keyed on;
* ``session_id`` — a gateway handle that belongs to the WebSocket that made it.
  ``tui_gateway/ws.py`` reaps a transport's sessions in its ``finally``, so the
  handle is dead the moment that connection closes.

Persisting the handle and reusing it later therefore *always* failed with
"session not found". Every turn now re-attaches on its own connection.
"""

from __future__ import annotations

import pytest

from realestate.hermes.sessions import _attach, trusted_context


class FakeRpc:
    """Records calls and replays scripted JSON-RPC frames."""

    def __init__(self, frames: dict[str, dict]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        return self.frames.get(method, {"error": {"code": -32601}})


RESUMED = {
    "result": {"session_id": "live-handle-2", "session_key": "durable-1", "resumed": "durable-1"}
}
CREATED = {
    "result": {"session_id": "live-handle-9", "stored_session_id": "durable-new"}
}
NOT_FOUND = {"error": {"code": 4001, "message": "session not found"}}


async def test_a_known_durable_session_is_resumed() -> None:
    rpc = FakeRpc({"session.resume": RESUMED})

    gateway, durable = await _attach(rpc, "durable-1", "sales")

    assert (gateway, durable) == ("live-handle-2", "durable-1")
    assert [m for m, _ in rpc.calls] == ["session.resume"]


async def test_resume_carries_the_profile() -> None:
    # The session lives in the Role profile's own state database, so resuming
    # without the profile would not find it.
    rpc = FakeRpc({"session.resume": RESUMED})

    await _attach(rpc, "durable-1", "sales")

    assert rpc.calls[0][1]["profile"] == "sales"
    assert rpc.calls[0][1]["session_id"] == "durable-1"


async def test_the_durable_id_is_preserved_across_a_resume() -> None:
    """A new handle must not change the id the Role binding is keyed on."""
    rpc = FakeRpc({"session.resume": RESUMED})

    _, durable = await _attach(rpc, "durable-1", "sales")

    assert durable == "durable-1"


async def test_no_durable_session_yet_creates_one() -> None:
    # Hermes persists the session row lazily, on the first prompt, so a cycle's
    # first turn legitimately has nothing to resume.
    rpc = FakeRpc({"session.create": CREATED})

    gateway, durable = await _attach(rpc, "", "sales")

    assert (gateway, durable) == ("live-handle-9", "durable-new")
    assert [m for m, _ in rpc.calls] == ["session.create"]


async def test_an_unresumable_session_falls_back_to_create() -> None:
    rpc = FakeRpc({"session.resume": NOT_FOUND, "session.create": CREATED})

    gateway, durable = await _attach(rpc, "durable-gone", "sales")

    assert [m for m, _ in rpc.calls] == ["session.resume", "session.create"]
    assert (gateway, durable) == ("live-handle-9", "durable-new")


async def test_a_truncated_session_is_rebuilt_from_the_supplied_product_history() -> None:
    truncated = {
        "result": {
            "session_id": "live-truncated",
            "session_key": "durable-old",
            "message_count": 2,
        }
    }
    rpc = FakeRpc({"session.resume": truncated, "session.create": CREATED})
    seed = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, ¿en qué te ayudo?"},
        {"role": "user", "content": "precio"},
        {"role": "assistant", "content": "tres millones"},
    ]

    gateway, durable = await _attach(
        rpc, "durable-old", "sales", seed, minimum_history_messages=4
    )

    assert (gateway, durable) == ("live-handle-9", "durable-new")
    assert [method for method, _ in rpc.calls] == ["session.resume", "session.create"]
    assert rpc.calls[1][1]["messages"] == seed


async def test_trusted_context_seeds_a_new_session() -> None:
    """The WhatsApp profile name reaches the Model only this way (amendment 3)."""
    rpc = FakeRpc({"session.create": CREATED})
    seed = trusted_context(profile_name="Cliente Demo")

    await _attach(rpc, "", "sales", seed)

    messages = rpc.calls[0][1]["messages"]
    assert [m["role"] for m in messages] == ["system"]
    assert "Cliente Demo" in messages[0]["content"]
    # Named as product context so the Model does not answer it as a message,
    # and not offered as proof of who the person is.
    assert "no es un mensaje de la persona" in messages[0]["content"]
    assert "no es un dato verificado de identidad" in messages[0]["content"].lower()


async def test_a_resumed_session_is_not_re_seeded() -> None:
    """It is already in that session's history; re-seeding would repeat it.

    A reaped gateway handle causes a resume on almost every turn, so this is the
    common path rather than an edge case.
    """
    rpc = FakeRpc({"session.resume": RESUMED})

    await _attach(rpc, "durable-1", "sales", trusted_context(profile_name="Cliente Demo"))

    assert "messages" not in rpc.calls[0][1]


async def test_no_profile_name_seeds_nothing() -> None:
    # Meta does not always send a profile name. Absent is absent; the guide then
    # asks for a name without offering one.
    rpc = FakeRpc({"session.create": CREATED})

    for absent in (None, "", "   "):
        assert trusted_context(profile_name=absent) == []

    await _attach(rpc, "", "sales", trusted_context(profile_name=None))
    assert "messages" not in rpc.calls[0][1]


async def test_a_failed_create_is_reported() -> None:
    from realestate.hermes.sessions import SessionError

    rpc = FakeRpc({"session.create": {"error": {"message": "boom"}}})

    with pytest.raises(SessionError, match="session.create failed"):
        await _attach(rpc, "", "sales")


async def test_a_create_without_identifiers_is_reported() -> None:
    from realestate.hermes.sessions import SessionError

    rpc = FakeRpc({"session.create": {"result": {"session_id": "x"}}})

    with pytest.raises(SessionError, match="no usable identifiers"):
        await _attach(rpc, "", "sales")
