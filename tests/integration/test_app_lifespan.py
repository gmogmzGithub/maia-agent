"""The Stage 0 process lifecycle (ADR-0007).

One process owns the API path and the background loop, and the lifespan is what
wires them. Three properties are asserted here because each one has a failure
mode that only shows up in production:

* the three responsibilities in a tick are **isolated**. A Telegram outage must
  not stop the product answering Leads — but the failure must still be re-raised
  once the others have run, or /health would report a healthy loop.
* teardown releases every dependency even when an earlier release throws.
  Chaining them bare would leak PostgreSQL connections across a restart loop.
* an unreachable Hermes is a startup *warning*, not a fatal error: the operator
  has to be able to reach /health and read the reason.

The database URL points at the real test database; nothing else here needs a
live dependency, because a failing probe is exactly what the startup report is
supposed to survive.
"""

from __future__ import annotations

import logging

import pytest

from realestate.app import _log_startup_report, create_app, lifespan
from realestate.config import Settings, get_settings
from tests.conftest import DATABASE_URL


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "DATABASE_URL": DATABASE_URL,
        # Nothing may reach a real Meta, Telegram, Google or Hermes from here.
        "HERMES_BASE_URL": "http://127.0.0.1:9",
        "HERMES_DASHBOARD_SESSION_TOKEN": "test-token",
        "META_ACCESS_TOKEN": "",
        "META_PHONE_NUMBER_ID": "",
        "TELEGRAM_BOT_TOKEN": "",
        "GOOGLE_CALENDAR_CREDENTIALS": "",
        "GOOGLE_CALENDAR_ID": "",
        "OBJECT_STORAGE_ACCESS_KEY_ID": "test-access",
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
        "WORKER_ENABLED": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def unstarted_loop(monkeypatch: pytest.MonkeyPatch):
    """Build the composed tick without letting the loop run it on its own.

    The tick's isolation is the thing under test, so it is invoked directly;
    a concurrently running loop would race every assertion about call counts.
    """
    from realestate.worker.loop import BackgroundLoop

    async def do_not_start(self) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(BackgroundLoop, "start", do_not_start)


# -- Wiring -------------------------------------------------------------------


async def test_the_lifespan_wires_every_dependency_onto_the_app() -> None:
    app = create_app(settings())

    async with lifespan(app):
        for attribute in (
            "database",
            "artifacts",
            "media_storage",
            "hermes",
            "whatsapp",
            "calendar",
            "appointment_policy",
            "telegram",
            "admin_worker",
            "worker",
            "broker_notifier",
            "background_loop",
        ):
            assert getattr(app.state, attribute) is not None, attribute


async def test_the_appointment_policy_is_built_from_the_configured_schedule() -> None:
    app = create_app(
        settings(
            WEEKLY_SCHEDULE=(
                "mon=10:00-14:00;tue=nada;wed=nada;thu=nada;fri=nada;"
                "sat=nada;sun=nada"
            ),
            VISIT_MINUTES=45,
            BOOKING_HORIZON_DAYS=9,
            MAX_SLOT_CANDIDATES=4,
        )
    )

    async with lifespan(app):
        policy = app.state.appointment_policy
        assert policy.visit_minutes == 45
        assert policy.horizon_days == 9
        assert policy.max_candidates == 4
        assert len(policy.schedule.ranges[0]) == 1


async def test_a_malformed_schedule_fails_loudly_at_startup() -> None:
    """An unquoted ``;`` once truncated the schedule to Monday alone and nothing
    complained — a week of missing availability, silently."""
    from realestate.domain.availability import ScheduleError

    app = create_app(settings(WEEKLY_SCHEDULE="mon=10:00-14:00"))

    with pytest.raises(ScheduleError):
        async with lifespan(app):
            pass  # pragma: no cover - the context never opens


# -- The composed tick --------------------------------------------------------


class RecordingWorker:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.ticks = 0

    async def tick(self) -> None:
        self.ticks += 1
        if self.error is not None:
            raise self.error


async def run_tick(app) -> Exception | None:  # noqa: ANN001
    """Invoke the composed tick the loop was built with, reporting its failure."""
    try:
        await app.state.background_loop._tick()
    except Exception as exc:  # noqa: BLE001 - the assertion is about which one
        return exc
    return None


async def test_all_four_responsibilities_run_in_one_tick(unstarted_loop) -> None:
    app = create_app(settings(WORKER_ENABLED=True))

    async with lifespan(app):
        app.state.worker = RecordingWorker()
        app.state.followup_worker = RecordingWorker()
        app.state.admin_worker = RecordingWorker()
        app.state.broker_notifier = RecordingWorker()

        assert await run_tick(app) is None
        assert (
            app.state.worker.ticks,
            app.state.followup_worker.ticks,
            app.state.admin_worker.ticks,
            app.state.broker_notifier.ticks,
        ) == (1, 1, 1, 1)


async def test_a_failing_administrative_tick_does_not_stop_answering_leads(
    caplog: pytest.LogCaptureFixture, unstarted_loop
) -> None:
    app = create_app(settings(WORKER_ENABLED=True))

    async with lifespan(app):
        app.state.worker = RecordingWorker()
        app.state.followup_worker = RecordingWorker()
        app.state.admin_worker = RecordingWorker(RuntimeError("Telegram is down"))
        app.state.broker_notifier = RecordingWorker()

        with caplog.at_level(logging.ERROR, logger="realestate.app"):
            failure = await run_tick(app)

        # Lead work and the Broker's notifications still ran…
        assert app.state.worker.ticks == 1
        assert app.state.followup_worker.ticks == 1
        assert app.state.broker_notifier.ticks == 1
        # …and the failure is still re-raised, so /health counts the iteration
        # as failed rather than reporting a healthy loop.
        assert isinstance(failure, RuntimeError)
        assert "administrative" in caplog.text


async def test_the_first_failure_is_the_one_reported(unstarted_loop) -> None:
    app = create_app(settings(WORKER_ENABLED=True))

    async with lifespan(app):
        app.state.worker = RecordingWorker(RuntimeError("lead"))
        app.state.followup_worker = RecordingWorker(RuntimeError("follow-up"))
        app.state.admin_worker = RecordingWorker(RuntimeError("administrative"))
        app.state.broker_notifier = RecordingWorker(RuntimeError("broker"))

        failure = await run_tick(app)

        assert str(failure) == "lead"
        # Every responsibility still got its turn.
        assert app.state.followup_worker.ticks == 1
        assert app.state.admin_worker.ticks == 1
        assert app.state.broker_notifier.ticks == 1


async def test_a_disabled_worker_runs_an_idle_loop_instead() -> None:
    from realestate.worker.loop import idle_tick

    app = create_app(settings(WORKER_ENABLED=False))

    async with lifespan(app):
        assert app.state.background_loop._tick is idle_tick
        assert app.state.background_loop.state.running is False


async def test_an_enabled_worker_starts_the_loop() -> None:
    app = create_app(settings(WORKER_ENABLED=True, WORKER_POLL_SECONDS=30.0))

    async with lifespan(app):
        assert app.state.background_loop.state.running is True

    assert app.state.background_loop.state.running is False


# -- The startup report -------------------------------------------------------


class Probe:
    def __init__(self, report: object) -> None:
        self._report = report

    async def check_health(self) -> object:
        return self._report


class Report:
    def __init__(self, ok: bool, detail: str, status: object = None) -> None:
        self.ok = ok
        self.detail = detail
        self.status = status


async def test_a_healthy_startup_reports_each_dependency_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings())
    app.state.database = Probe(Report(True, "PostgreSQL reachable"))
    app.state.hermes = Probe(Report(True, "Hermes 0.20.0 reachable"))
    app.state.media_storage = Probe(Report(True, "Object storage reachable"))

    with caplog.at_level(logging.INFO, logger="realestate.app"):
        await _log_startup_report(app)

    assert "PostgreSQL reachable" in caplog.text
    assert "Hermes 0.20.0 reachable" in caplog.text


async def test_an_unreachable_hermes_is_a_warning_not_a_refusal_to_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The product must still start so an operator can reach /health."""
    from realestate.hermes.client import HermesStatus

    app = create_app(settings())
    app.state.database = Probe(Report(False, "PostgreSQL is not reachable"))
    app.state.hermes = Probe(
        Report(False, "nothing answered", status=HermesStatus.UNREACHABLE)
    )
    app.state.media_storage = Probe(Report(False, "Object storage unreachable"))

    with caplog.at_level(logging.WARNING, logger="realestate.app"):
        await _log_startup_report(app)

    assert "PostgreSQL is not reachable" in caplog.text
    assert "unreachable" in caplog.text


# -- Teardown -----------------------------------------------------------------


class Releasable:
    def __init__(self, name: str, order: list[str], error: Exception | None = None) -> None:
        self.name = name
        self._order = order
        self._error = error

    async def release(self) -> None:
        self._order.append(self.name)
        if self._error is not None:
            raise self._error


async def test_a_failing_release_does_not_skip_the_database_disposal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Chaining teardown bare would leak PostgreSQL connections across a restart
    loop until the server refused new clients."""
    order: list[str] = []
    app = create_app(settings())

    async with lifespan(app):
        app.state.background_loop.stop = Releasable("loop", order).release
        app.state.hermes.aclose = Releasable(
            "hermes", order, RuntimeError("client already gone")
        ).release
        app.state.whatsapp.aclose = Releasable("whatsapp", order).release
        app.state.telegram.aclose = Releasable("telegram", order).release
        app.state.database.dispose = Releasable("database", order).release

        with caplog.at_level(logging.ERROR, logger="realestate.app"):
            pass

    assert order == ["loop", "hermes", "whatsapp", "telegram", "database"]


async def test_every_teardown_failure_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []
    app = create_app(settings())

    with caplog.at_level(logging.ERROR, logger="realestate.app"):
        async with lifespan(app):
            app.state.background_loop.stop = Releasable(
                "loop", order, RuntimeError("loop stuck")
            ).release
            app.state.database.dispose = Releasable(
                "database", order, RuntimeError("engine gone")
            ).release

    assert "background loop" in caplog.text
    assert "database engine" in caplog.text


# -- The factory --------------------------------------------------------------


def test_the_factory_registers_every_route_group() -> None:
    paths = set(create_app(settings()).openapi()["paths"])

    assert {"/health", "/upload", "/webhooks/whatsapp", "/internal/plugin/health"} <= paths


def test_no_browser_origin_may_reach_the_application() -> None:
    """CORS stays disabled (P-051); the upload page is same-origin only."""
    from fastapi.middleware.cors import CORSMiddleware

    app = create_app(settings())

    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_the_factory_falls_back_to_the_environment_settings() -> None:
    get_settings.cache_clear()

    app = create_app()

    assert app.state.settings is get_settings()


def test_the_product_logger_gets_a_handler_so_the_startup_report_is_visible() -> None:
    """uvicorn leaves the root logger without one, which would hide product logs."""
    product = logging.getLogger("realestate")
    existing = list(product.handlers)
    propagate = product.propagate
    for handler in existing:
        product.removeHandler(handler)
    try:
        create_app(settings())
        assert product.handlers
        assert product.level == logging.DEBUG
        assert product.propagate is False
        # A second application does not stack a second handler.
        before = len(product.handlers)
        create_app(settings())
        assert len(product.handlers) == before
    finally:
        for handler in list(product.handlers):
            product.removeHandler(handler)
        for handler in existing:
            product.addHandler(handler)
        # The factory turned propagation off on the way through; caplog in every
        # later module depends on it being back on.
        product.propagate = propagate
