"""One Hermes turn, including the In-flight Message Reconciliation window.

``run_turn`` is where the product's hardest ordering rules live, and none of
them are visible from a passing conversation:

* the durable session id is published *before* ``prompt.submit``, or the very
  first tool call in the turn is rejected as ``forbidden``;
* injection prefers ``session.redirect`` and falls back to ``session.steer``;
  when neither takes the text, nothing is reported as injected and the message
  stays queued for the next FIFO cycle;
* ``on_adopted`` fires before the next poll, or the same pending message is
  offered again and folded in twice.

Driven against scripted JSON-RPC frames rather than a live runtime, so the
ordering is asserted directly instead of inferred from a model's reply.
"""

from __future__ import annotations

import pytest

from realestate.hermes.sessions import (
    TURN_TIMEOUT_SECONDS,
    SessionError,
    RoleSession,
    _inject,
    dated_prompt,
    role_prompt,
    run_turn,
    submit_prompt,
)
from realestate.db.models import AgentRole

CREATED = {"result": {"session_id": "handle-1", "stored_session_id": "durable-1"}}
RESUMED = {"result": {"session_id": "handle-2", "session_key": "durable-1"}}
SUBMITTED = {"result": {"status": "accepted"}}


def event(kind: str, session_id: str = "handle-1", **payload: object) -> dict:
    return {"session_id": session_id, "type": kind, "payload": payload}


class FakeRpc:
    """Scripted JSON-RPC responses plus a queue of events to hand back.

    ``None`` in the event script is a quiet poll — exactly what lets the
    reconciliation window run while the model is still thinking.
    """

    def __init__(self, frames: dict[str, object], events: list[dict | None]) -> None:
        self._frames = frames
        self._events = list(events)
        self.calls: list[tuple[str, dict]] = []
        self.polls = 0

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        frame = self._frames.get(method, {"error": {"code": -32601}})
        if isinstance(frame, list):
            # A scripted sequence: each call consumes the next answer.
            return frame.pop(0) if frame else {"error": {"code": -32601}}
        return frame

    async def receive_event_or_none(self, timeout: float) -> dict | None:
        self.polls += 1
        if not self._events:
            raise AssertionError("run_turn polled past the end of the script")
        return self._events.pop(0)

    @property
    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


class FakeClient:
    """Stands in for HermesClient: hands out one connection, records entry."""

    def __init__(self, rpc: FakeRpc) -> None:
        self._rpc = rpc
        self.sessions_opened = 0
        self.closed = False

    def session(self) -> "FakeClient":
        self.sessions_opened += 1
        return self

    async def __aenter__(self) -> FakeRpc:
        return self._rpc

    async def __aexit__(self, *exc_info: object) -> None:
        self.closed = True


def unbound() -> RoleSession:
    return RoleSession(gateway_session_id="", hermes_session_id="", role=AgentRole.SALES)


def bound(durable: str = "durable-1") -> RoleSession:
    return RoleSession(
        gateway_session_id="", hermes_session_id=durable, role=AgentRole.SALES
    )


def turn(events: list[dict | None], **frames: object) -> tuple[FakeClient, FakeRpc]:
    rpc = FakeRpc({"session.create": CREATED, "prompt.submit": SUBMITTED, **frames}, events)
    return FakeClient(rpc), rpc


# -- The happy path -----------------------------------------------------------


async def test_a_turn_returns_the_completed_text() -> None:
    client, rpc = turn([event("message.complete", text="hola, claro que sí")])

    result = await run_turn(client, unbound(), "hola", profile="sales")

    assert result.text == "hola, claro que sí"
    assert result.hermes_session_id == "durable-1"
    assert rpc.methods == ["session.create", "prompt.submit"]


async def test_deltas_are_joined_when_the_completion_carries_no_text() -> None:
    client, _ = turn(
        [
            event("message.delta", text="hola"),
            event("message.delta", text=", claro"),
            event("message.complete"),
        ]
    )

    result = await run_turn(client, unbound(), "hola", profile="sales")

    assert result.text == "hola, claro"


async def test_the_completion_text_wins_over_the_accumulated_deltas() -> None:
    client, _ = turn(
        [event("message.delta", text="parcial"), event("message.complete", text="final")]
    )

    assert (await run_turn(client, unbound(), "hola", profile="sales")).text == "final"


async def test_the_tools_the_model_used_are_reported() -> None:
    client, _ = turn(
        [
            event("tool.start", name="get_property_information"),
            event("tool.start", name="get_available_slots"),
            event("message.complete", text="listo"),
        ]
    )

    result = await run_turn(client, unbound(), "hola", profile="sales")

    assert result.tools_used == ["get_property_information", "get_available_slots"]


async def test_a_nameless_tool_event_is_ignored_rather_than_recorded_blank() -> None:
    client, _ = turn([event("tool.start"), event("message.complete", text="listo")])

    assert (await run_turn(client, unbound(), "hola", profile="sales")).tools_used == []


async def test_the_prompt_carries_the_gateway_handle_not_the_durable_id() -> None:
    client, rpc = turn([event("message.complete", text="ok")])

    await run_turn(client, unbound(), "hola", profile="sales")

    submitted = dict(rpc.calls)["prompt.submit"]
    assert submitted["session_id"] == "handle-1"
    assert submitted["text"] == role_prompt("hola", role=AgentRole.SALES)


def test_only_sales_turns_receive_the_property_freshness_context() -> None:
    sales = role_prompt("hola", role=AgentRole.SALES)

    assert "get_property_information" in sales
    assert sales.endswith("\nhola")
    assert role_prompt("hola", role=AgentRole.ADMINISTRATIVE) == "hola"


async def test_events_for_another_session_on_the_socket_are_ignored() -> None:
    client, _ = turn(
        [
            event("message.complete", session_id="someone-else", text="not ours"),
            event("message.complete", text="ours"),
        ]
    )

    assert (await run_turn(client, unbound(), "hola", profile="sales")).text == "ours"


async def test_an_event_without_a_session_id_is_accepted() -> None:
    # Some runtime events are connection-scoped rather than session-scoped.
    client, _ = turn([event("message.complete", session_id=None, text="ours")])

    assert (await run_turn(client, unbound(), "hola", profile="sales")).text == "ours"


# -- Publishing the binding before the model can call a tool ------------------


async def test_the_durable_id_is_published_before_the_prompt_is_submitted() -> None:
    """A tool call in the first model step resolves Role from this binding."""
    order: list[str] = []

    class OrderingRpc(FakeRpc):
        async def call(self, method: str, params: dict) -> dict:
            order.append(method)
            return await super().call(method, params)

    rpc = OrderingRpc(
        {"session.create": CREATED, "prompt.submit": SUBMITTED},
        [event("message.complete", text="ok")],
    )

    async def on_attached(durable: str) -> None:
        order.append(f"bind:{durable}")

    await run_turn(FakeClient(rpc), unbound(), "hola", profile="sales", on_attached=on_attached)

    assert order == ["session.create", "bind:durable-1", "prompt.submit"]


async def test_an_unchanged_durable_id_is_not_re_bound() -> None:
    # A resume returns the same durable id on nearly every turn; rewriting the
    # binding each time would be a pointless write on the hot path.
    client, _ = turn(
        [event("message.complete", session_id="handle-2", text="ok")],
        **{"session.resume": RESUMED},
    )
    bindings: list[str] = []

    await run_turn(
        client, bound(), "hola", profile="sales", on_attached=_recorder(bindings)
    )

    assert bindings == []


async def test_a_replaced_session_re_points_the_binding() -> None:
    client, _ = turn(
        [event("message.complete", text="ok")],
        **{"session.resume": {"error": {"message": "session not found"}}},
    )
    bindings: list[str] = []

    await run_turn(
        client, bound("gone"), "hola", profile="sales", on_attached=_recorder(bindings)
    )

    assert bindings == ["durable-1"]


# -- Failures -----------------------------------------------------------------


async def test_a_rejected_prompt_is_reported() -> None:
    client, _ = turn([], **{"prompt.submit": {"error": {"message": "busy"}}})

    with pytest.raises(SessionError, match="prompt.submit failed"):
        await run_turn(client, unbound(), "hola", profile="sales")


async def test_a_turn_that_errors_mid_stream_is_reported() -> None:
    client, _ = turn([event("message.complete", status="error", error="model refused")])

    with pytest.raises(SessionError, match="model refused"):
        await run_turn(client, unbound(), "hola", profile="sales")


async def test_an_errored_completion_without_a_reason_still_raises() -> None:
    client, _ = turn([event("message.complete", status="error")])

    with pytest.raises(SessionError, match="Hermes turn failed"):
        await run_turn(client, unbound(), "hola", profile="sales")


async def test_a_turn_that_never_completes_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged runtime must not hold an Inbox lease open forever."""
    import realestate.hermes.sessions as sessions

    monkeypatch.setattr(sessions, "time", _clock(0.0, TURN_TIMEOUT_SECONDS + 1.0))
    client, _ = turn([None])

    with pytest.raises(SessionError, match="did not complete the turn in time"):
        await run_turn(client, unbound(), "hola", profile="sales")


# -- In-flight Message Reconciliation (P-034) ---------------------------------


async def test_a_late_message_is_folded_into_the_live_turn() -> None:
    client, rpc = turn(
        [None, event("message.complete", text="respondido todo")],
        **{"session.redirect": {"result": {"status": "redirected"}}},
    )
    adopted: list[int] = []

    result = await run_turn(
        client,
        unbound(),
        "hola",
        profile="sales",
        on_poll=_offer_once("y el precio?"),
        on_adopted=_appender(adopted),
        window_seconds=30.0,
    )

    assert result.injected == ["y el precio?"]
    assert adopted == [1]
    assert "session.redirect" in rpc.methods


async def test_adoption_happens_before_the_next_poll() -> None:
    """Otherwise the same still-pending message is seen again and injected twice."""
    sequence: list[str] = []
    client, _ = turn(
        [None, None, event("message.complete", text="ok")],
        **{"session.redirect": {"result": {"status": "redirected"}}},
    )

    pending: list[str | None] = ["y el precio?", None]

    async def on_poll() -> str | None:
        sequence.append("poll")
        return pending.pop(0) if pending else None

    async def on_adopted() -> None:
        sequence.append("adopt")

    await run_turn(
        client,
        unbound(),
        "hola",
        profile="sales",
        on_poll=on_poll,
        on_adopted=on_adopted,
        window_seconds=30.0,
    )

    assert sequence == ["poll", "adopt", "poll"]


async def test_steer_is_used_when_redirect_is_refused() -> None:
    client, rpc = turn(
        [None, event("message.complete", text="ok")],
        **{
            "session.redirect": {"error": {"code": -32601}},
            "session.steer": {"result": {"status": "queued"}},
        },
    )

    result = await run_turn(
        client,
        unbound(),
        "hola",
        profile="sales",
        on_poll=_offer_once("y el precio?"),
        window_seconds=30.0,
    )

    assert result.injected == ["y el precio?"]
    assert rpc.methods.count("session.steer") == 1


async def test_text_neither_primitive_accepts_is_left_queued() -> None:
    """Reported as *not* injected, so the message stays Pending for the next
    FIFO cycle rather than being swallowed by a turn that ignored it."""
    client, _ = turn(
        [None, event("message.complete", text="ok")],
        **{
            "session.redirect": {"result": {"status": "rejected"}},
            "session.steer": {"result": {"status": "rejected"}},
        },
    )
    adopted: list[int] = []

    result = await run_turn(
        client,
        unbound(),
        "hola",
        profile="sales",
        on_poll=_offer_once("y el precio?"),
        on_adopted=_appender(adopted),
        window_seconds=30.0,
    )

    assert result.injected == []
    assert adopted == []


async def test_nothing_pending_injects_nothing() -> None:
    client, rpc = turn([None, event("message.complete", text="ok")])

    async def nothing() -> str | None:
        return None

    result = await run_turn(
        client, unbound(), "hola", profile="sales", on_poll=nothing, window_seconds=30.0
    )

    assert result.injected == []
    assert "session.redirect" not in rpc.methods


async def test_no_reconciliation_window_means_no_polling_callback() -> None:
    """``window_seconds`` defaults to 0: the administrative worker never folds."""
    client, _ = turn([None, event("message.complete", text="ok")])
    polled: list[int] = []

    async def on_poll() -> str | None:
        polled.append(1)
        return None

    await run_turn(client, unbound(), "hola", profile="sales", on_poll=on_poll)

    assert polled == []


async def test_injection_after_the_window_closes_is_not_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import realestate.hermes.sessions as sessions

    # Started at 0, the first quiet poll lands at 10s with a 5s window.
    monkeypatch.setattr(sessions, "time", _clock(0.0, 10.0))
    client, rpc = turn([None, event("message.complete", text="ok")])

    result = await run_turn(
        client,
        unbound(),
        "hola",
        profile="sales",
        on_poll=_offer_once("tarde"),
        window_seconds=5.0,
    )

    assert result.injected == []
    assert "session.redirect" not in rpc.methods


# -- The injection primitive in isolation -------------------------------------


@pytest.mark.parametrize("status", ["redirected", "queued"])
async def test_redirect_accepts_both_of_its_states(status: str) -> None:
    rpc = FakeRpc({"session.redirect": {"result": {"status": status}}}, [])

    assert await _inject(rpc, "handle-1", "texto") is True
    assert rpc.methods == ["session.redirect"]


async def test_a_redirect_that_only_reports_redirected_is_not_a_steer_state() -> None:
    # "redirected" is not in steer's accepted set, so a runtime answering it to
    # a steer call must not be read as acceptance.
    rpc = FakeRpc(
        {
            "session.redirect": {"error": {"code": -32601}},
            "session.steer": {"result": {"status": "redirected"}},
        },
        [],
    )

    assert await _inject(rpc, "handle-1", "texto") is False


async def test_injection_falls_through_both_primitives_before_giving_up() -> None:
    rpc = FakeRpc({}, [])

    assert await _inject(rpc, "handle-1", "texto") is False
    assert rpc.methods == ["session.redirect", "session.steer"]


# -- The dated prompt ---------------------------------------------------------


def test_the_prompt_is_stamped_with_today_in_spanish() -> None:
    """Without it the Model guesses at "el viernes" and books the wrong week."""
    from datetime import date

    stamped = dated_prompt("el viernes por la tarde", today=date(2026, 8, 7))

    first, _, rest = stamped.partition("\n")
    assert "viernes" in first and "07/08/2026" in first and "2026-08-07" in first
    # The Lead's own words are untouched below the stamp.
    assert rest == "el viernes por la tarde"


def test_every_weekday_has_a_spanish_name() -> None:
    from datetime import date, timedelta

    monday = date(2026, 8, 3)
    names = [
        dated_prompt("x", today=monday + timedelta(days=offset)).split(" ")[6]
        for offset in range(7)
    ]

    assert names == [
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    ]


# -- submit_prompt shares the same lifecycle ----------------------------------


async def test_submit_prompt_runs_a_turn_with_no_reconciliation_window() -> None:
    client, rpc = turn([event("message.complete", text="hola")])

    result = await submit_prompt(client, unbound(), "hola", profile="admin")

    assert result.text == "hola"
    assert dict(rpc.calls)["session.create"]["profile"] == "admin"


async def test_submit_prompt_reports_the_durable_session_back() -> None:
    client, _ = turn([event("message.complete", text="hola")])
    bindings: list[str] = []

    result = await submit_prompt(
        client, unbound(), "hola", on_attached=_recorder(bindings)
    )

    assert bindings == ["durable-1"]
    assert result.hermes_session_id == "durable-1"


# -- helpers ------------------------------------------------------------------


def _offer_once(text: str):  # noqa: ANN202
    offered = [text]

    async def on_poll() -> str | None:
        return offered.pop(0) if offered else None

    return on_poll


def _clock(*readings: float):  # noqa: ANN202
    """A stand-in for the ``time`` module that walks a scripted monotonic clock.

    Patched onto the module rather than onto ``time.monotonic`` itself, which is
    global state pytest also depends on.
    """
    import types

    remaining = list(readings)

    def monotonic() -> float:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return types.SimpleNamespace(monotonic=monotonic)


def _recorder(sink: list[str]):  # noqa: ANN202
    async def on_attached(durable: str) -> None:
        sink.append(durable)

    return on_attached


def _appender(sink: list[int]):  # noqa: ANN202
    async def on_adopted() -> None:
        sink.append(1)

    return on_adopted
