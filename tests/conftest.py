"""Shared test fixtures.

Tests come in two kinds:

* **Offline** — pure logic, always run.
* **Live** — exercise the real Compose topology (PostgreSQL, Hermes, and the
  Product application). These skip when a dependency is not up, so the suite
  is runnable on a cold machine, but they are the tests that actually prove a
  checkpoint's exit condition.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# The standalone plugin is a separate distribution installed into the Hermes
# virtualenv, not the product one. Import it from the source tree for tests.
sys.path.insert(0, str(REPO_ROOT / "plugin"))


def _load_dotenv() -> dict[str, str]:
    env_file = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


DOTENV = _load_dotenv()


def env(key: str, default: str = "") -> str:
    return os.environ.get(key) or DOTENV.get(key, default)


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _hostport(url: str, default_port: int) -> tuple[str, int]:
    netloc = url.split("://", 1)[-1].split("/", 1)[0]
    netloc = netloc.rpartition("@")[2]  # drop any user:password@ prefix
    host, _, port = netloc.partition(":")
    return host, int(port) if port else default_port


HERMES_BASE_URL = env("HERMES_BASE_URL", "http://127.0.0.1:9119")
# The suite runs inside Product's container. APP_HOST is a bind address, not a
# client address, so always probe the process through loopback.
APP_BASE_URL = "http://127.0.0.1:8080"

_DEV_DATABASE_URL = env(
    "DATABASE_URL",
    "postgresql+psycopg://realestate:realestate@127.0.0.1:5433/realestate",
)


def _test_database_url() -> str:
    """Tests get their own database on the same PostgreSQL instance.

    Fixtures truncate freely, so sharing the development database would destroy
    the Developer's uploaded Property Documents on every run. Override with
    TEST_DATABASE_URL if a different target is wanted.
    """
    explicit = env("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base, _, name = _DEV_DATABASE_URL.rpartition("/")
    name = name.split("?", 1)[0]
    return f"{base}/{name}_test"


DATABASE_URL = _test_database_url()

requires_hermes = pytest.mark.skipif(
    not _port_open(*_hostport(HERMES_BASE_URL, 9119)),
    reason="the Hermes container is not running",
)
requires_app = pytest.mark.skipif(
    not _port_open(*_hostport(APP_BASE_URL, 8080)),
    reason="the Product container is not running",
)
requires_postgres = pytest.mark.skipif(
    not _port_open(*_hostport(DATABASE_URL, 5433)),
    reason="the PostgreSQL container is not running",
)


def _ensure_test_database() -> None:
    """Create the test database and migrate it to head, once per run."""
    import psycopg
    from sqlalchemy.engine import make_url

    url = make_url(DATABASE_URL)
    admin = url.set(database="postgres").render_as_string(hide_password=False)
    dsn = admin.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if not exists:
            connection.execute(f'CREATE DATABASE "{url.database}"')

    from alembic import command
    from alembic.config import Config

    # Built programmatically rather than from alembic.ini on purpose. env.py
    # calls fileConfig() whenever a config file is named, and fileConfig
    # disables every logger the ini does not mention — including the product's,
    # which then emits nothing for the rest of the session and makes any test
    # that asserts on a log line silently vacuous.
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    # migrations/env.py reads the URL from settings, so point those at the
    # test database for the duration of the upgrade.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    try:
        from realestate.config import get_settings

        get_settings.cache_clear()
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


if _port_open(*_hostport(DATABASE_URL, 5433)):
    _ensure_test_database()


def migration_config(url: str):  # noqa: ANN201
    """An Alembic config pointed at one database, built programmatically.

    Not from alembic.ini, for the reason ``_ensure_test_database`` gives above:
    ``fileConfig`` silences every logger the ini does not mention.
    """
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def recreate_database(name: str) -> str:
    """Drop and recreate one database, returning its URL.

    Shared by the migration suites, which each need a database nobody else is
    connected to so they can walk revisions in both directions.
    """
    import psycopg
    from sqlalchemy.engine import make_url

    def url_for(database: str) -> str:
        return (
            make_url(DATABASE_URL)
            .set(database=database)
            .render_as_string(hide_password=False)
        )

    admin = url_for("postgres").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        connection.execute(f'CREATE DATABASE "{name}"')
    return url_for(name)


@contextmanager
def database_at_revision(name: str, revision: str):  # noqa: ANN201
    """A fresh database migrated to *revision*, with its Alembic config.

    Yields ``(config, engine)``. The ``DATABASE_URL`` swap and the settings
    cache clear are the delicate part — ``migrations/env.py`` reads the URL from
    settings — so they live here once rather than in each migration suite.
    """
    import os

    from alembic import command
    from sqlalchemy import create_engine

    from realestate.config import get_settings

    url = recreate_database(name)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    config = migration_config(url)
    engine = None
    try:
        command.upgrade(config, revision)
        engine = create_engine(url, future=True)
        yield config, engine
    finally:
        if engine is not None:
            engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def product_logs_reach_caplog():
    """Let caplog see the product's log lines.

    ``create_app`` gives the ``realestate`` logger its own handler and stops it
    propagating, so uvicorn does not print every line twice. caplog's handler
    lives on the root logger, so without this any assertion about a warning the
    product emits would pass vacuously against an empty log.

    Done once, here: the factory only touches the logger when it has no handler
    yet, so priming it keeps propagation on for every ``create_app`` afterwards.
    """
    import logging

    import realestate.app  # noqa: F401  (importing it runs the factory once)

    product = logging.getLogger("realestate")
    previous = product.propagate
    product.propagate = True
    yield
    product.propagate = previous


@pytest.fixture(scope="session")
def hermes_token() -> str:
    return env("HERMES_DASHBOARD_SESSION_TOKEN")


@pytest.fixture(scope="session")
def plugin_token() -> str:
    return env("PLUGIN_API_TOKEN")


async def larevia_organization_id(session):  # noqa: ANN001, ANN201
    """The Organization every commercial fixture row belongs to (ADR-0019).

    Created by migration 0012, not by fixtures: a test that invented its own
    Organization would not be exercising the scoping the product actually uses.
    """
    from sqlalchemy import select

    from realestate.db.models import LAREVIA_SLUG, Organization

    organization_id = await session.scalar(
        select(Organization.id).where(Organization.slug == LAREVIA_SLUG)
    )
    assert organization_id is not None, "run `alembic upgrade head` on the test database"
    return organization_id


async def provision_property_administrator(session) -> None:  # noqa: ANN001
    """Give the ``developer`` login an Administrator member row.

    The Property surfaces authenticate exactly as they always did, but
    authorization now resolves the login to an Organization member and refuses
    anything that does not administer (ADR-0046). A fixture that skipped this
    would be asserting on a 403.
    """
    from realestate.domain.commercial.organization import (
        DirectoryPlan,
        OrganizationDirectory,
    )

    await OrganizationDirectory(session).reconcile(
        DirectoryPlan(
            administrators=("developer",), advisors=(), default_advisor=None
        )
    )
    # Stage 9: an unbound WhatsApp number, Telegram bot or hostname is refused
    # rather than defaulted to the only Organization, so a fixture that skipped
    # this would be asserting on that refusal (ADR-0050).
    from tests.fixtures import commercial

    await commercial.bind_channels(session)
    await commercial.ensure_entitlements(session)


async def reset_property_inventory(session) -> None:  # noqa: ANN001
    """Empty the Property inventory, dependants first.

    Appointments and availability snapshots carry a foreign key to a Property,
    so a fixture that deletes only ``properties`` fails outright as soon as
    another suite has left a booking behind. Spelled once here so every suite
    clears the same set and the order the tests run in stops mattering.
    """
    from sqlalchemy import text

    for table in (
        "analytics.projection_runs",
        "analytics.domain_events",
        "analytics.analytics_outbox",
        "analytics.funnel_aggregates",
        "sponsorship_report_links",
        "sponsorship_contact_attributions",
        "sponsored_exposure_counters",
        "sponsorship_delivery_days",
        "sponsored_eligibility_records",
        "sponsorship_capacity_reservations",
        "sponsorship_quotes",
        "sponsorship_campaigns",
        "marketing_touches",
        "campaign_audience_members",
        "development_campaigns",
        "reactivation_candidates",
        "appointments",
        "availability_snapshots",
        "listing_media",
        "listing_offers",
        "catalog_listings",
        "properties",
        "unit_models",
        "developments",
    ):
        await session.execute(text(f"DELETE FROM {table}"))


async def age_pending_inbox(database) -> None:  # noqa: ANN001
    """Age pending messages past the two-second collection window.

    Shifts each timestamp by a constant so relative arrival order — the FIFO
    guarantee under test elsewhere — is preserved. Spelled once here because
    every worker suite has to step over that window before it can tick.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from realestate.db.models import InboxMessage, InboxStatus

    async with database.session_scope() as session:
        for row in (await session.execute(select(InboxMessage))).scalars():
            if row.status == InboxStatus.PENDING.value:
                row.persisted_at = row.persisted_at - timedelta(seconds=10)
                row.next_attempt_at = None
        await session.commit()


@pytest.fixture
async def operation(tmp_path: Path):
    """A Stage 3 operation: a provisioned team, calendars, one Property.

    Every Stage 3 suite needs exactly this and used to carry its own copy, so a
    change to the setup — another table to reset, a second artifacts root — meant
    editing seven files with nothing failing if one was missed. A pytest fixture
    in ``conftest`` is inherited, so the suites simply ask for ``operation``.
    """
    from realestate.db.engine import Database
    from tests.fixtures import visits

    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await visits.reset(session)
        built = await visits.build(session, tmp_path / "artifacts")
        await session.commit()
    yield database, built
    await database.dispose()
