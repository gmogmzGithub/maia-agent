"""The in-process background loop lifecycle (ADR-0007)."""

from __future__ import annotations

import asyncio

from realestate.worker.loop import BackgroundLoop


async def test_loop_starts_ticks_and_stops() -> None:
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1

    loop = BackgroundLoop(tick=tick, interval_seconds=0.01)
    await loop.start()
    assert loop.state.running

    await asyncio.sleep(0.06)
    await loop.stop()

    assert ticks >= 2
    assert loop.state.ticks >= 2
    assert loop.state.failures == 0
    assert not loop.state.running


async def test_a_failing_iteration_does_not_kill_the_loop() -> None:
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")

    loop = BackgroundLoop(tick=tick, interval_seconds=0.01)
    await loop.start()
    await asyncio.sleep(0.06)
    await loop.stop()

    assert calls >= 2, "the loop must keep running after a failed iteration"
    assert loop.state.failures == 1
    assert loop.state.last_error is not None
    assert "transient" in loop.state.last_error


async def test_stop_is_idempotent() -> None:
    async def tick() -> None:
        return None

    loop = BackgroundLoop(tick=tick, interval_seconds=0.01)
    await loop.start()
    await loop.stop()
    await loop.stop()

    assert not loop.state.running


async def test_starting_a_running_loop_does_not_start_a_second_one() -> None:
    """Two tasks on one lane would claim the same Inbox work twice."""
    ticks: list[int] = []

    async def tick() -> None:
        ticks.append(1)

    loop = BackgroundLoop(tick=tick, interval_seconds=0.01)
    await loop.start()
    first = loop._task
    try:
        await loop.start()
        assert loop._task is first
    finally:
        await loop.stop()


async def test_the_idle_tick_claims_no_work() -> None:
    """The Checkpoint 0 placeholder, still used whenever WORKER_ENABLED is off."""
    from realestate.worker.loop import idle_tick

    assert await idle_tick() is None


async def test_a_cancelled_tick_stops_the_loop_rather_than_counting_as_a_failure() -> None:
    import asyncio

    async def tick() -> None:
        raise asyncio.CancelledError

    loop = BackgroundLoop(tick=tick, interval_seconds=0.01)
    await loop.start()
    await asyncio.sleep(0.05)

    await loop.stop()

    assert loop.state.failures == 0
    assert loop.state.running is False
