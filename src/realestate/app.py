"""FastAPI application factory and Stage 0 process lifecycle (ADR-0007).

One local process runs both responsibilities: the API path (this app) and the
in-process background loop. They share one PostgreSQL schema and one set of
domain modules but stay separate in code.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
import httpx

from realestate.api import health as health_api
from realestate.api import admin as admin_api
from realestate.api import analytics as analytics_api
from realestate.api import crm as crm_api
from realestate.api import catalog as catalog_api
from realestate.api import external_inventory as external_inventory_api
from realestate.api import engagement as engagement_api
from realestate.api import operations as operations_api
from realestate.api import platform as platform_api
from realestate.api import plugin as plugin_api
from realestate.api import public_site as public_site_api
from realestate.api import public_proxy as public_proxy_api
from realestate.api import sponsorship as sponsorship_api
from realestate.api import upload as upload_api
from realestate.api import webhooks as webhooks_api
from realestate.channels.google.calendar import GoogleCalendar
from realestate.channels.telegram.client import TelegramClient
from realestate.channels.whatsapp.client import WhatsAppClient
from realestate.config import Settings, get_settings
from realestate.db.engine import Database
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.admin_work import AdminWorkService
from realestate.domain.availability import WeeklySchedule
from realestate.domain.commercial.organization import OrganizationDirectory
from realestate.domain.platform.bootstrap import (
    BootstrapEnvironment,
    PlatformBootstrap,
)
from realestate.domain.platform.credentials import SecretResolver
from realestate.domain.platform.providers import (
    OrganizationEasyBrokerAdapters,
    OrganizationGoogleCalendarDirectories,
    OrganizationTelegramClients,
)
from realestate.domain.platform.runtime import OrganizationAppointmentPolicies
from realestate.domain.platform.whatsapp import (
    OrganizationMetaTemplateSources,
    OrganizationWhatsAppClients,
)
from realestate.db.models import IntegrationProvider
from realestate.domain.catalog.storage import LocalMediaStorage
from realestate.domain.external_inventory.easybroker import EasyBrokerAdapter
from realestate.domain.scheduling.calendars import GoogleCalendarDirectory
from realestate.domain.properties import ArtifactStore, CatalogStore
from realestate.hermes import HermesClient
from realestate.hosts import host_of as site_host_of
from realestate.worker.broker import OrganizationBrokerNotifiers
from realestate.worker.external_inventory import ExternalInventoryCleanupWorker
from realestate.worker.analytics import AnalyticsWorker
from realestate.worker.engagement import EngagementWorker
from realestate.worker.followups import LeadFollowUpWorker
from realestate.worker.loop import BackgroundLoop, idle_tick
from realestate.worker.operations import OrganizationOperationsWorkers
from realestate.worker.platform import PlatformWorker
from realestate.worker.telegram import OrganizationTelegramAdminWorkers
from realestate.worker.upkeep import CommercialUpkeepWorker
from realestate.worker.whatsapp import WhatsAppWorker

logger = logging.getLogger(__name__)


def _log_level(name: str) -> int:
    level = getattr(logging, name.strip().upper(), None)
    return level if isinstance(level, int) else logging.INFO


async def _reconcile_directory(app: FastAPI) -> None:
    """Make the Organization's member rows match the configured team.

    Best-effort on purpose. An unreachable or unmigrated database must not stop
    the process, because an operator needs /health to read *why*. What is not
    best-effort is the plan itself: an inconsistent one raises before this runs,
    the same way a malformed weekly schedule does.
    """
    plan = app.state.directory_plan
    if not plan.logins:
        logger.warning(
            "No Organization members are configured. Set "
            "ORGANIZATION_ADMIN_LOGINS and ORGANIZATION_ADVISOR_LOGINS; until "
            "then the commercial surfaces refuse every credential."
        )
        return
    try:
        async with app.state.database.session_scope() as session:
            result = await OrganizationDirectory(session).reconcile(plan)
    except Exception:
        logger.exception(
            "Could not reconcile Organization members; the commercial "
            "surfaces will refuse credentials until this succeeds"
        )
        return
    if result.changed:
        logger.info(
            "Organization members reconciled (created=%s, updated=%s, "
            "deactivated=%s)",
            list(result.created),
            list(result.updated),
            list(result.deactivated),
        )
    else:
        logger.info(
            "Organization members already match configuration (%d member(s))",
            len(plan.logins),
        )


async def _bootstrap_platform(app: FastAPI) -> None:
    """Bind the founding Organization's channels from the process environment.

    Runs *before* the member reconciliation, because Stage 9 refuses a login
    whose Organization is not Active and this is what asserts that status on a
    database restored from an older dump.

    Best-effort for the same reason the directory reconciliation is: an operator
    needs ``/health`` to say why, and an installation with no founding
    Organization is a legitimate state in which this does nothing.
    """
    settings: Settings = app.state.settings
    environment = BootstrapEnvironment(
        slug=settings.platform_bootstrap_organization_slug,
        whatsapp_phone_number_id=settings.meta_phone_number_id,
        whatsapp_business_account_id=settings.meta_waba_id,
        telegram_bot_id=app.state.telegram.bot_id,
        public_site_host=site_host_of(settings.site_public_origin),
        credential_references={
            IntegrationProvider(provider): name
            for provider, name in settings.bootstrap_credential_references.items()
        },
    )
    try:
        async with app.state.database.session_scope() as session:
            report = await PlatformBootstrap(
                session, app.state.secret_resolver
            ).reconcile(environment)
    except Exception:
        logger.exception(
            "Could not reconcile the founding Organization's channel bindings; "
            "inbound WhatsApp, Telegram and public-site traffic will be refused "
            "until this succeeds"
        )
        return
    app.state.bootstrap_organization_id = report.organization_id
    if report.changed:
        logger.info(
            "Platform bootstrap bound %s and named %s",
            list(report.bound),
            list(report.references),
        )
    if report.skipped:
        logger.error(
            "Platform bootstrap left %s alone: another Organization holds it",
            list(report.skipped),
        )
    if report.organization_id is None:
        logger.warning(
            "No Organization has the slug %r, so nothing in the process "
            "environment applies to any Organization. Provision one before "
            "accepting traffic.",
            environment.slug,
        )


async def _log_startup_report(app: FastAPI) -> None:
    """Report each dependency at startup so a missing piece is obvious.

    An unavailable or incompatible Hermes Runtime is a warning, not a fatal
    error: the product must still start so an operator can reach /health and
    read the reason.
    """
    # Both probes are network round trips and neither depends on the other, so
    # they do not need to be added to each other's startup latency.
    database, hermes = await asyncio.gather(
        app.state.database.check_health(),
        app.state.hermes.check_health(),
    )
    if database.ok:
        logger.info("PostgreSQL: %s", database.detail)
    else:
        logger.error("PostgreSQL: %s", database.detail)

    if hermes.ok:
        logger.info("Hermes Runtime: %s", hermes.detail)
    else:
        # Product deliberately starts in degraded mode when Hermes is absent.
        # In Compose, Hermes also starts just after Product because it joins
        # Product's network namespace, so this can be a harmless startup race.
        logger.warning("Hermes Runtime [%s]: %s", hermes.status.value, hermes.detail)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "Starting product harness (worker_enabled=%s, worker_poll_seconds=%.2f, "
        "hermes_base_url=%s, sales_profile=%s, admin_profile=%s)",
        settings.worker_enabled,
        settings.worker_poll_seconds,
        settings.hermes_base_url,
        settings.sales_profile,
        settings.admin_profile,
    )
    logger.debug(
        "Runtime boundaries: product=container, hermes=container, "
        "hermes_transport=loopback-json-rpc-websocket"
    )

    # Validated before anything else touches it: a default Advisor login that
    # does not exist would silently send every new Opportunity to the
    # Assignment Queue, which is worse than refusing to start.
    app.state.directory_plan = settings.directory_plan
    app.state.database = Database(settings.database_url)
    app.state.artifacts = ArtifactStore(Path(settings.artifact_root))
    app.state.property_catalog = CatalogStore(Path(settings.property_catalog_root))
    app.state.media_storage = LocalMediaStorage(
        Path(settings.listing_media_root), Path(settings.listing_media_cache_root)
    )
    app.state.easybroker = EasyBrokerAdapter(
        api_key=settings.easybroker_api_key,
        base_url=settings.easybroker_base_url,
        mls_access_confirmed=settings.easybroker_mls_access_confirmed,
        retention_permission_confirmed=(
            settings.easybroker_retention_permission_confirmed
        ),
    )
    app.state.hermes = HermesClient.from_settings(settings)
    app.state.public_site_proxy = httpx.AsyncClient(
        base_url=settings.public_site_base_url,
        timeout=30.0,
        follow_redirects=False,
    )
    app.state.whatsapp = WhatsAppClient(
        access_token=settings.meta_access_token,
        phone_number_id=settings.meta_phone_number_id,
        graph_version=settings.meta_graph_version,
        base_url=settings.meta_graph_base_url,
    )
    # Kept for /health, which probes the one calendar an operator configured.
    app.state.calendar = GoogleCalendar(
        credentials_path=settings.google_calendar_credentials,
        calendar_id=settings.google_calendar_id,
    )
    # Every scheduling decision goes through the directory instead: since Stage
    # 3 an appointment belongs to an Advisor and is written to *their* calendar,
    # so "the calendar" is no longer a single thing (ADR-0048).
    app.state.calendars = GoogleCalendarDirectory(
        credentials_path=settings.google_calendar_credentials
    )
    # A malformed schedule must fail loudly at startup, not silently narrow
    # availability — see the truncation guard in domain/availability.py.
    app.state.appointment_policy = AppointmentPolicy(
        schedule=WeeklySchedule.parse(settings.weekly_schedule, settings.timezone),
        visit_minutes=settings.visit_minutes,
        horizon_days=settings.booking_horizon_days,
        max_candidates=settings.max_slot_candidates,
        day_of_reminder_hour=settings.appointment_day_of_reminder_hour,
    )
    app.state.telegram = TelegramClient(bot_token=settings.telegram_bot_token)
    # The only object that reads a secret's value. A deployment backed by a
    # secret manager replaces this and nothing else (ADR-0052).
    app.state.secret_resolver = SecretResolver()
    app.state.bootstrap_organization_id = None
    # Bind the founding Organization and reconcile its members before any
    # worker can claim operational work. Provider directories below need the
    # resolved bootstrap id to keep the legacy environment fallback bounded.
    await _bootstrap_platform(app)
    await _reconcile_directory(app)
    app.state.whatsapp_clients = OrganizationWhatsAppClients(
        app.state.secret_resolver,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
        legacy_access_token=settings.meta_access_token,
        graph_version=settings.meta_graph_version,
        base_url=settings.meta_graph_base_url,
    )
    app.state.meta_templates = OrganizationMetaTemplateSources(
        app.state.secret_resolver,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
        legacy_access_token=settings.meta_access_token,
        graph_version=settings.meta_graph_version,
        base_url=settings.meta_graph_base_url,
    )
    app.state.easybroker_sources = OrganizationEasyBrokerAdapters(
        app.state.secret_resolver,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
        legacy_api_key=settings.easybroker_api_key,
        legacy_mls_access_confirmed=settings.easybroker_mls_access_confirmed,
        legacy_retention_permission_confirmed=(
            settings.easybroker_retention_permission_confirmed
        ),
        base_url=settings.easybroker_base_url,
    )
    app.state.calendar_directories = OrganizationGoogleCalendarDirectories(
        app.state.secret_resolver,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
        legacy_credentials_path=settings.google_calendar_credentials,
    )
    app.state.appointment_policies = OrganizationAppointmentPolicies(
        app.state.appointment_policy,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
    )
    app.state.telegram_clients = OrganizationTelegramClients(
        app.state.secret_resolver,
        bootstrap_organization_id=app.state.bootstrap_organization_id,
        legacy_bot_token=settings.telegram_bot_token,
    )
    app.state.admin_worker = OrganizationTelegramAdminWorkers(
        database=app.state.database,
        hermes=app.state.hermes,
        clients=app.state.telegram_clients,
        admin_profile=settings.admin_profile,
    )
    app.state.worker = WhatsAppWorker(
        database=app.state.database,
        hermes=app.state.hermes,
        whatsapp=app.state.whatsapp_clients,
        sales_profile=settings.sales_profile,
        schedule=app.state.appointment_policies,
        max_concurrent=settings.max_concurrent_conversations,
    )
    app.state.broker_notifier = OrganizationBrokerNotifiers(
        database=app.state.database,
        clients=app.state.telegram_clients,
        policies=app.state.appointment_policies,
        digest_hour=settings.broker_digest_hour,
        reminder_minutes=settings.broker_reminder_minutes_before,
    )
    app.state.followup_worker = LeadFollowUpWorker(database=app.state.database)
    # Human-handoff escalation, internal alert delivery, and visit reminders.
    app.state.operations_worker = OrganizationOperationsWorkers(
        database=app.state.database,
        clients=app.state.telegram_clients,
        policies=app.state.appointment_policies,
    )
    # Property Need staleness, day-28 dormancy and conversation-content expiry.
    # Paces itself: these rules have 28- and 90-day horizons and the loop ticks
    # once a second.
    app.state.upkeep_worker = CommercialUpkeepWorker(database=app.state.database)
    app.state.external_inventory_cleanup_worker = ExternalInventoryCleanupWorker(
        database=app.state.database,
        source=app.state.easybroker_sources,
    )
    app.state.engagement_worker = EngagementWorker(
        database=app.state.database,
        activation_approved=settings.marketing_outbound_activated,
    )
    # Analytics emission, the projection pass, sponsorship day accounting and
    # quote expiry. Paced by its own interval: a measurement pass has no
    # business running once a second.
    app.state.analytics_worker = AnalyticsWorker(database=app.state.database)
    # Support-grant expiry and the per-Organization usage projection. Its own
    # object because both rules outlive one tick and neither belongs to a
    # Brokerage Organization's own work.
    app.state.platform_worker = PlatformWorker(database=app.state.database)

    async def tick() -> None:
        # Lead work, follow-ups, Administrative work, and the Broker's
        # notifications share the loop but not their capacity limits (P-037).
        # Each is isolated: otherwise a Telegram outage would stop answering
        # Leads or enqueueing due WhatsApp follow-ups.
        failure: Exception | None = None
        async def recover() -> None:
            async with app.state.database.session_scope() as session:
                recovered = await AdminWorkService(
                    session,
                    app.state.calendars,
                    app.state.appointment_policy.schedule,
                    app.state.appointment_policy.day_of_reminder_hour,
                ).recover_pending_attempts()
                if recovered:
                    logger.error(
                        "Recovered %d interrupted Calendar attempt(s) as NeedsReview",
                        recovered,
                    )

        for name, responsibility in (
            ("recovery", recover),
            ("lead", app.state.worker.tick),
            ("lead follow-ups", app.state.followup_worker.tick),
            ("commercial upkeep", app.state.upkeep_worker.tick),
            (
                "external inventory cleanup",
                app.state.external_inventory_cleanup_worker.tick,
            ),
            ("reactivation and campaigns", app.state.engagement_worker.tick),
            ("analytics and sponsorship", app.state.analytics_worker.tick),
            ("platform upkeep", app.state.platform_worker.tick),
            ("human operations", app.state.operations_worker.tick),
            ("administrative", app.state.admin_worker.tick),
            ("broker notifications", app.state.broker_notifier.tick),
        ):
            try:
                await responsibility()
            except Exception as exc:
                logger.exception("The %s tick failed", name)
                failure = failure or exc
        if failure is not None:
            # Re-raised once the others have run, so /health still counts the
            # iteration as failed instead of reporting a healthy loop.
            raise failure

    app.state.background_loop = BackgroundLoop(
        tick=tick if settings.worker_enabled else idle_tick,
        interval_seconds=settings.worker_poll_seconds,
    )

    if settings.worker_enabled:
        await app.state.background_loop.start()
    else:
        logger.warning("Background worker is disabled; API stays up but no Inbox polling runs")
    await _log_startup_report(app)

    try:
        yield
    finally:
        logger.info("Stopping product harness")
        # Each step runs even if an earlier one fails. Chaining them bare would
        # let a failing client teardown skip database disposal, leaking
        # PostgreSQL connections across a restart loop until the server refuses
        # new clients.
        for what, release in (
            ("background loop", app.state.background_loop.stop),
            ("Hermes client", app.state.hermes.aclose),
            ("public site proxy", app.state.public_site_proxy.aclose),
            ("EasyBroker adapter", app.state.easybroker.aclose),
            ("Organization EasyBroker adapters", app.state.easybroker_sources.aclose),
            ("Meta template source", app.state.meta_templates.aclose),
            ("WhatsApp client", app.state.whatsapp.aclose),
            ("Organization WhatsApp clients", app.state.whatsapp_clients.aclose),
            ("Telegram client", app.state.telegram.aclose),
            ("Organization Telegram clients", app.state.telegram_clients.aclose),
            ("database engine", app.state.database.dispose),
        ):
            try:
                await release()
            except Exception:
                logger.exception("Releasing the %s on shutdown failed", what)


def create_app(settings: Settings | None = None) -> FastAPI:
    # uvicorn configures its own loggers but leaves the root logger without a
    # handler, which would hide the product's startup report below WARNING.
    settings = settings or get_settings()
    if not logging.getLogger("realestate").handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        product_logger = logging.getLogger("realestate")
        product_logger.addHandler(handler)
        product_logger.propagate = False
    logging.getLogger("realestate").setLevel(_log_level(settings.log_level))

    app = FastAPI(
        title="Real Estate Lead Agent — Product Harness",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS stays disabled (P-051): no browser origin may reach this application.
    app.state.settings = settings
    app.include_router(health_api.router)
    app.include_router(admin_api.router)
    app.include_router(crm_api.router)
    app.include_router(catalog_api.router)
    app.include_router(external_inventory_api.router)
    app.include_router(engagement_api.router)
    app.include_router(analytics_api.router)
    app.include_router(sponsorship_api.router)
    app.include_router(operations_api.router)
    # Two routers from one module and deliberately so: the platform's own
    # surface authenticates with the platform credential, while the panel an
    # Organization Administrator reads authenticates as they always did.
    app.include_router(platform_api.router)
    app.include_router(platform_api.organization_router)
    app.include_router(plugin_api.router)
    app.include_router(public_site_api.router)
    app.include_router(upload_api.router)
    app.include_router(webhooks_api.router)
    # Last on purpose: it catches only public website paths after Product's
    # own health, webhook, plugin and operator routes had the first match.
    app.include_router(public_proxy_api.router)
    return app


app = create_app()
