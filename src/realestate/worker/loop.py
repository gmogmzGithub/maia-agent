"""The in-process background loop (ADR-0007, P-030).

Stage 0 runs one application process. The API path durably records inbound work
and returns promptly; this loop performs Inbox, Outbox, Follow-up, and Hermes
processing afterwards. The two responsibilities stay separate in code so they
can later become separate process roles without splitting the application.

Checkpoint 0 establishes only the lifecycle: a supervised task that starts with
the application, ticks on a fixed interval, survives an iteration that raises,
and stops cleanly on shutdown. It claims no work yet.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

Tick = Callable[[], Awaitable[None]]


@dataclass
class BackgroundLoopState:
    running: bool = False
    ticks: int = 0
    failures: int = 0
    last_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class BackgroundLoop:
    """A single supervised asyncio task with a start/stop lifecycle."""

    def __init__(self, tick: Tick, interval_seconds: float = 1.0) -> None:
        self._tick = tick
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.state = BackgroundLoopState()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self.state = BackgroundLoopState(running=True)
        self._task = asyncio.create_task(self._run(), name="realestate-background-loop")
        logger.info("Background loop started (interval=%.2fs)", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self.state.running = False
        logger.info("Background loop stopped after %d tick(s)", self.state.ticks)

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._tick()
                self.state.ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a failing iteration must not kill the loop
                self.state.failures += 1
                self.state.last_error = f"{exc.__class__.__name__}: {exc}"
                logger.exception("Background loop iteration failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue


async def idle_tick() -> None:
    """Checkpoint 0 placeholder: the loop runs but claims no work yet."""
    return None
