"""How one Organization operates, as a versioned document.

Every stage before this one put behaviour in the process environment: the service
area, the weekly bookable schedule, the default Advisor, the brand's public
origin, the Telegram allowlist. That works for one brokerage because the process
*is* the brokerage. With two, the environment can only describe one of them, and
the other would silently inherit whatever the first was configured with.

So configuration becomes a record, and the shape is deliberately not a settings
table:

* **one row is the whole document.** Reading March's configuration means reading
  March's row, not replaying a change log nobody kept. Rolling back means
  recording the previous document again;
* **recording the same document twice is a no-op.** That is what makes a
  restarted provisioning run idempotent, and it is enforced on a checksum of the
  canonical form rather than on field equality, so a reordered JSON object is
  recognised as the same document;
* **a version needs a written reason.** A configuration change nobody explained
  is indistinguishable from a mistake three months later;
* **no credential ever appears here.** Those are references and they live in
  :mod:`realestate.domain.platform.credentials`. A document that could carry a
  token would end up in an export.

The bootstrap Organization is the one exception to "the environment describes
nobody", and it is bounded exactly like the credential fallback: process
configuration answers for the founding Organization *only*, identified by
comparing an Organization id. Every other Organization reads its document or gets
a refusal. That asymmetry is the honest description of an installation that grew
from one brokerage rather than being provisioned, and there is a test whose whole
purpose is to prove the second Organization cannot reach the first one's
environment (ADR-0051).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import OrganizationConfigurationVersion
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.platform.authority import PlatformOperator, require_reason

logger = logging.getLogger(__name__)

#: The document's own sections. A key outside this set is refused rather than
#: stored: a document that accepts anything cannot be validated, cannot be
#: rendered, and cannot be told apart from a place somebody put a secret.
ALLOWED_SECTIONS = frozenset(
    {
        # Public identity: working name, legal name, the site's public origin.
        "brand",
        # Where the Organization operates: municipalities, the service-area note.
        "service_area",
        # The weekly bookable schedule, visit length, booking horizon, time zone.
        "scheduling",
        # The founding team: administrator and advisor logins, the default
        # Advisor. Reconciled into member rows exactly as configuration is.
        "team",
        # Which channels the Organization uses, and their external identifiers.
        # Identifiers only — the credentials that open them are references.
        "channels",
        # Which integrations are expected to be configured, by provider name.
        "integrations",
        # The operational ceilings the Organization is permitted: recipient caps,
        # quiet hours, campaign limits. Distinct from entitlements, which say
        # what was *bought*; these say what the operation is allowed to do with
        # it.
        "limits",
        # Free-form operator notes about the Organization. Read by humans only.
        "notes",
        # Where the document came from, when it was not written by an operator.
        "origin",
    }
)

#: Keys whose presence anywhere in the document means somebody put a credential
#: in it. Checked recursively, because the section allowlist above does not stop
#: ``channels.whatsapp.access_token``.
FORBIDDEN_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)


class ConfigurationMissing(CommercialError):
    """This Organization has no recorded configuration.

    A refusal, not an empty document. An Organization operating on defaults
    nobody chose is the failure mode this module exists to remove.
    """

    message = (
        "Esta organización no tiene configuración registrada. Regístrala antes "
        "de ponerla a operar."
    )


class InvalidConfiguration(CommercialError):
    """The submitted document is not one this product will store."""

    message = "La configuración enviada no es válida."


@dataclass(frozen=True)
class RecordConfiguration:
    """One complete statement of how an Organization operates."""

    organization_id: uuid.UUID
    document: Mapping[str, Any]
    reason: str
    command_key: str


@dataclass(frozen=True)
class ConfigurationView:
    """A recorded version, as an operator or a caller reads it."""

    organization_id: uuid.UUID
    version: int
    document: Mapping[str, Any]
    checksum: str
    note: str
    recorded_by: str
    recorded_at: datetime
    is_current: bool

    def section(self, name: str) -> Mapping[str, Any]:
        """One section, or an empty mapping when the document omits it.

        Empty rather than raising: a document that says nothing about campaigns
        is a valid document, and every caller of a section already treats an
        absent value as "not configured".
        """
        value = self.document.get(name)
        return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ConfigurationHistory:
    """Every version, newest first, with the current one identified."""

    organization_id: uuid.UUID
    versions: tuple[ConfigurationView, ...] = field(default_factory=tuple)

    @property
    def current(self) -> ConfigurationView | None:
        return next((item for item in self.versions if item.is_current), None)


def canonical(document: Mapping[str, Any]) -> str:
    """The document's canonical JSON form, for hashing and comparison."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)


def checksum_of(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(document).encode()).hexdigest()


def _reject_credentials(value: Any, path: str = "") -> None:
    """Walk the document refusing any key that looks like a secret's home.

    Recursive because the danger is not a top-level ``token`` — nobody writes
    that — it is ``channels.whatsapp.access_token``, added by somebody solving a
    real problem in the most obvious way.
    """
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).lower()
            if any(marker in name for marker in FORBIDDEN_KEY_MARKERS):
                raise InvalidConfiguration(
                    f"La configuración no puede contener credenciales "
                    f"({path}{key}). Registra una referencia de secreto en su "
                    "lugar."
                )
            _reject_credentials(nested, f"{path}{key}.")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_credentials(nested, f"{path}{index}.")


def validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """The document, normalised, or a refusal naming what is wrong."""
    if not isinstance(document, Mapping) or not document:
        raise InvalidConfiguration("La configuración no puede estar vacía.")
    unknown = sorted(set(map(str, document)) - ALLOWED_SECTIONS)
    if unknown:
        raise InvalidConfiguration(
            "La configuración contiene secciones desconocidas: "
            + ", ".join(unknown)
            + ". Las secciones válidas son: "
            + ", ".join(sorted(ALLOWED_SECTIONS))
            + "."
        )
    _reject_credentials(document)
    # Round-tripped through JSON so what is stored is exactly what was
    # validated: a value the serialiser would coerce must be coerced *before*
    # the checksum, or a re-record of the same document would look different.
    normalised: dict[str, Any] = json.loads(canonical(document))
    return normalised


class OrganizationConfiguration:
    """The versioned configuration of one Organization.

    Hides: the version counter, the single-current partial index, the canonical
    checksum, the credential rejection, and the bootstrap Organization's bounded
    environment fallback.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
    ) -> None:
        self._session = session
        self._bootstrap_organization_id = bootstrap_organization_id

    async def record(
        self,
        operator: PlatformOperator,
        command: RecordConfiguration,
        *,
        at: datetime | None = None,
    ) -> ConfigurationView:
        """Record a new version, or replay the current one. Does not commit.

        Idempotent twice over, and the two are different guarantees worth having
        separately:

        * the same ``command_key`` replays its own version, which is what makes a
          double-submitted operator form harmless;
        * the same *document* — whatever key it arrives under — records no new
          version, which is what makes a restarted provisioning run stop after
          the step that already succeeded.
        """
        reason = require_reason(command.reason)
        document = validate_document(command.document)
        digest = checksum_of(document)
        moment = at or utc_now()

        replay = await self._session.scalar(
            select(OrganizationConfigurationVersion)
            .where(
                OrganizationConfigurationVersion.organization_id
                == command.organization_id
            )
            .where(
                OrganizationConfigurationVersion.command_key == command.command_key
            )
        )
        if replay is not None:
            return self._view(replay)

        rows = list(
            await self._session.scalars(
                select(OrganizationConfigurationVersion)
                .where(
                    OrganizationConfigurationVersion.organization_id
                    == command.organization_id
                )
                .order_by(OrganizationConfigurationVersion.version.desc())
                .with_for_update()
            )
        )
        current = next((row for row in rows if row.is_current), None)
        if current is not None and current.checksum == digest:
            logger.debug(
                "Configuration for Organization %s is unchanged; no version "
                "recorded",
                command.organization_id,
            )
            return self._view(current)

        # The outgoing version stops being current before the new one is
        # inserted: the partial unique index permits one, and inserting first
        # would collide with the row about to be superseded.
        for row in rows:
            row.is_current = False
        await self._session.flush()

        version = (rows[0].version + 1) if rows else 1
        record = OrganizationConfigurationVersion(
            organization_id=command.organization_id,
            version=version,
            document=document,
            checksum=digest,
            is_current=True,
            note=reason,
            recorded_by=operator.label,
            recorded_at=moment,
            command_key=command.command_key,
        )
        self._session.add(record)
        await self._session.flush()

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RecordOrganizationConfiguration",
            subject_type="Organization",
            subject_id=str(command.organization_id),
            details={
                "version": version,
                "checksum": digest,
                "sections": sorted(document),
                "reason": reason,
            },
            commit=False,
        )
        logger.info(
            "Recorded configuration version %d for Organization %s",
            version,
            command.organization_id,
        )
        return self._view(record)

    async def current(self, organization_id: uuid.UUID) -> ConfigurationView:
        """The Organization's current document, or a refusal."""
        row = await self._current_row(organization_id)
        if row is None:
            raise ConfigurationMissing()
        return self._view(row)

    async def try_current(
        self, organization_id: uuid.UUID
    ) -> ConfigurationView | None:
        """The current document, or ``None`` where absence is an answer."""
        row = await self._current_row(organization_id)
        return self._view(row) if row is not None else None

    async def history(self, organization_id: uuid.UUID) -> ConfigurationHistory:
        """Every version, newest first."""
        rows = await self._session.scalars(
            select(OrganizationConfigurationVersion)
            .where(
                OrganizationConfigurationVersion.organization_id == organization_id
            )
            .order_by(OrganizationConfigurationVersion.version.desc())
        )
        return ConfigurationHistory(
            organization_id=organization_id,
            versions=tuple(self._view(row) for row in rows),
        )

    async def read_for(self, actor: Actor) -> ConfigurationView:
        """The caller's own Organization's configuration.

        Takes an ``Actor`` rather than an id, so there is no argument an
        Administrator could pass to read another Organization's setup.
        """
        actor.require_administrator()
        return await self.current(actor.organization_id)

    def uses_process_environment(self, organization_id: uuid.UUID) -> bool:
        """Whether process configuration may answer for this Organization.

        The one place the bootstrap exception is decided. Every caller that
        considers falling back to a process setting asks this first, and an
        Organization that is not the founding one always gets ``False`` — which
        is what turns "inherit the environment" from a default into a refusal
        (ADR-0051).
        """
        return (
            self._bootstrap_organization_id is not None
            and organization_id == self._bootstrap_organization_id
        )

    async def _current_row(
        self, organization_id: uuid.UUID
    ) -> OrganizationConfigurationVersion | None:
        found: OrganizationConfigurationVersion | None = await self._session.scalar(
            select(OrganizationConfigurationVersion)
            .where(
                OrganizationConfigurationVersion.organization_id == organization_id
            )
            .where(OrganizationConfigurationVersion.is_current.is_(True))
        )
        return found

    @staticmethod
    def _view(row: OrganizationConfigurationVersion) -> ConfigurationView:
        return ConfigurationView(
            organization_id=row.organization_id,
            version=row.version,
            document=row.document,
            checksum=row.checksum,
            note=row.note,
            recorded_by=row.recorded_by,
            recorded_at=row.recorded_at,
            is_current=row.is_current,
        )
