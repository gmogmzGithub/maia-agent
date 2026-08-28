"""Stage 0 settings.

Secrets are loaded from the process environment or a local ``.env`` file that is
never committed (P-051). Nothing in this module carries a usable default for a
credential: an unset secret must fail loudly rather than silently authenticate.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only domain import in this module, and it points one way: no domain module
# imports config. Validating the plan on a settings property is what makes a
# default-Advisor login that does not exist fail at startup instead of silently
# sending every new Opportunity to the Assignment Queue — the same reason
# ``WeeklySchedule.parse`` raises rather than narrowing availability.
from realestate.domain.commercial.organization import DirectoryPlan


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Deterministic Backend persistence (ADR-0006) -----------------------
    database_url: str = Field(
        default="postgresql+psycopg://realestate:realestate@127.0.0.1:5433/realestate",
        alias="DATABASE_URL",
    )

    # --- Hermes Runtime boundary (ADR-0008) ---------------------------------
    hermes_base_url: str = Field(default="http://127.0.0.1:9119", alias="HERMES_BASE_URL")
    hermes_session_token: str = Field(default="", alias="HERMES_DASHBOARD_SESSION_TOKEN")
    hermes_pinned_version: str = Field(default="0.20.0", alias="HERMES_PINNED_VERSION")
    hermes_timeout_seconds: float = Field(default=10.0, alias="HERMES_TIMEOUT_SECONDS")

    # --- Plugin -> Product application boundary (ADR-0009) ------------------
    # The standalone Hermes plugin is a thin adapter running inside the Hermes
    # process. It authenticates to this application with a shared local token;
    # it never receives database or Calendar credentials.
    plugin_api_token: str = Field(default="", alias="PLUGIN_API_TOKEN")

    # --- Organization roles (ADR-0019, Stage 2) ------------------------------
    # Non-secret, explicit configuration: which authenticated logins are
    # Organization Administrators and which are Real Estate Advisors. This is
    # the bootstrap only. Somebody has to be an administrator before anybody can
    # create one, and the alternative — treating the first credential that
    # authenticates as privileged — is exactly the ambiguity Stage 2 removes.
    #
    # A login listed in both is an Administrator who also advises, which is how
    # "Santiago initially has both roles" is expressed without a third role.
    # Membership itself lives in PostgreSQL; these values are reconciled into it
    # at startup, idempotently and with an audit event.
    organization_admin_logins: str = Field(
        default="", alias="ORGANIZATION_ADMIN_LOGINS"
    )
    organization_advisor_logins: str = Field(
        default="", alias="ORGANIZATION_ADVISOR_LOGINS"
    )
    # The deterministic assignment fallback. Optional when there is exactly one
    # Advisor, because naming it twice would buy nothing.
    organization_default_advisor_login: str = Field(
        default="", alias="ORGANIZATION_DEFAULT_ADVISOR_LOGIN"
    )

    # Per-Advisor operational configuration, non-secret, reconciled into the
    # member table at startup exactly as the role lists are (ADR-0048).
    #
    # ``login=calendar-id`` pairs. An Advisor with no calendar has no
    # authoritative availability and cannot receive a visit — a refusal, never
    # an empty week treated as free. An Administrator can also set this per
    # person from the team surface, and configuration never clears what they
    # set.
    organization_member_calendars: str = Field(
        default="", alias="ORGANIZATION_MEMBER_CALENDARS"
    )
    # ``login=telegram-chat-id`` pairs, for the immediate operational alerts a
    # human handoff raises. Optional: without one the alert is still durable and
    # visible in the CRM, and the Administrators are told it could not be
    # delivered.
    organization_member_telegram_ids: str = Field(
        default="", alias="ORGANIZATION_MEMBER_TELEGRAM_IDS"
    )

    @property
    def directory_plan(self) -> DirectoryPlan:
        """The configured team, validated. Raises on an inconsistent plan."""
        return DirectoryPlan.from_configuration(
            administrators=self.organization_admin_logins,
            advisors=self.organization_advisor_logins,
            default_advisor=self.organization_default_advisor_login,
            calendars=self.organization_member_calendars,
            telegram_ids=self.organization_member_telegram_ids,
            # Stage 0's single calendar becomes the default Advisor's, so an
            # existing local setup keeps booking instead of quietly losing its
            # authority the moment appointments gained an owner.
            fallback_calendar_id=self.google_calendar_id,
        )

    # --- Property Document ingestion (P-045, P-051) --------------------------
    # Local Basic-auth secrets for the operational write surface. The JSON
    # mapping supports the current local setup; the pair is its single-account
    # compatibility fallback. Neither creates product Roles or web sessions.
    developer_basic_credentials_json: str = Field(
        default="", alias="DEVELOPER_BASIC_CREDENTIALS_JSON"
    )
    developer_basic_user: str = Field(default="", alias="DEVELOPER_BASIC_USER")
    developer_basic_password: str = Field(default="", alias="DEVELOPER_BASIC_PASSWORD")
    # Immutable content-addressed artifacts for accepted documents (P-050).
    artifact_root: str = Field(default="var/property-documents", alias="ARTIFACT_ROOT")
    # Public-safe, source-controlled current copies for human editing.
    property_catalog_root: str = Field(
        default="src/properties", alias="PROPERTY_CATALOG_ROOT"
    )
    # Approved Listing media and its derived local cache. These are storage
    # locations, not credentials; Compose mounts both under one durable volume.
    listing_media_root: str = Field(
        default="var/listing-media/originals", alias="LISTING_MEDIA_ROOT"
    )
    listing_media_cache_root: str = Field(
        default="var/listing-media/cache", alias="LISTING_MEDIA_CACHE_ROOT"
    )

    # --- Meta WhatsApp Cloud API (P-021, TC-003) -----------------------------
    meta_app_secret: str = Field(default="", alias="META_APP_SECRET")
    meta_verify_token: str = Field(default="", alias="META_VERIFY_TOKEN")
    meta_access_token: str = Field(default="", alias="META_ACCESS_TOKEN")
    meta_phone_number_id: str = Field(default="", alias="META_PHONE_NUMBER_ID")
    meta_graph_version: str = Field(default="v25.0", alias="META_GRAPH_VERSION")
    meta_graph_base_url: str = Field(
        default="https://graph.facebook.com", alias="META_GRAPH_BASE_URL"
    )

    # --- Appointments (P-054, P-055, P-056; see docs/decisions/checkpoint-3-inputs.md)
    google_calendar_credentials: str = Field(
        default="", alias="GOOGLE_CALENDAR_CREDENTIALS"
    )
    google_calendar_id: str = Field(default="", alias="GOOGLE_CALENDAR_ID")
    # The Broker's operating zone. Every time a Lead sees is rendered in it.
    timezone: str = Field(default="America/Mexico_City", alias="TIMEZONE")
    # The Weekly Bookable Schedule: one entry per day, empty means no visits.
    # Free calendar time outside these ranges is never offered (P-054).
    weekly_schedule: str = Field(
        default=(
            "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
            "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
        ),
        alias="WEEKLY_SCHEDULE",
    )
    visit_minutes: int = Field(default=90, alias="VISIT_MINUTES")
    booking_horizon_days: int = Field(default=8, alias="BOOKING_HORIZON_DAYS")
    # One availability result returns at most this many candidates (P-059).
    max_slot_candidates: int = Field(default=6, alias="MAX_SLOT_CANDIDATES")

    # --- Visit reminders (SAN-036 pending) -----------------------------------
    # The local hour the day-of reminder is due. Configuration rather than a
    # number chosen in code, because when a customer should be messaged is
    # Santiago's operational decision. Dispatch stays blocked until he
    # validates the cadence — see domain/scheduling/reminders.py.
    appointment_day_of_reminder_hour: int = Field(
        default=9, alias="APPOINTMENT_DAY_OF_REMINDER_HOUR"
    )

    # --- Broker notifications (amendment 2) ----------------------------------
    broker_digest_hour: int = Field(default=8, alias="BROKER_DIGEST_HOUR")
    broker_reminder_minutes_before: int = Field(
        default=90, alias="BROKER_REMINDER_MINUTES_BEFORE"
    )

    # --- Stage 0 worker limits (P-037) ---------------------------------------
    # At most three Lead Conversations execute in Hermes simultaneously.
    # Configuration, not a domain rule.
    max_concurrent_conversations: int = Field(
        default=3, alias="MAX_CONCURRENT_CONVERSATIONS"
    )

    # --- Hermes role profiles (ADR-0001, ADR-0013) ---------------------------
    # Each Role gets its own Hermes profile so its guide and tool surface stay
    # byte-stable, which preserves prompt caching.
    sales_profile: str = Field(default="sales", alias="HERMES_SALES_PROFILE")
    admin_profile: str = Field(default="admin", alias="HERMES_ADMIN_PROFILE")

    # --- Telegram Administrative Channel (P-040) -----------------------------
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    # Comma-separated Telegram numeric user ids for the Broker and Developer.
    # Both have identical authority during Stage 0 (ADR-0001).
    telegram_admin_ids: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")

    @property
    def admin_user_ids(self) -> frozenset[str]:
        return frozenset(
            part.strip() for part in self.telegram_admin_ids.split(",") if part.strip()
        )

    # --- Background loop (ADR-0007) -----------------------------------------
    worker_poll_seconds: float = Field(default=1.0, alias="WORKER_POLL_SECONDS")
    worker_enabled: bool = Field(default=True, alias="WORKER_ENABLED")
    log_level: str = Field(default="DEBUG", alias="LOG_LEVEL")

    @property
    def hermes_ws_url(self) -> str:
        """Authenticated local JSON-RPC WebSocket URL for the pinned runtime."""
        base = self.hermes_base_url.rstrip("/")
        scheme = "wss" if base.startswith("https://") else "ws"
        netloc = base.split("://", 1)[1]
        return f"{scheme}://{netloc}/api/ws"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
