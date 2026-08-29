"""Everything one Organization owns: handed over, or removed.

Two operations a managed platform has to be able to perform on demand, and both
of them are only possible because :mod:`realestate.domain.platform.scoping` wrote
down which tables hold an Organization's data. Neither walks the schema by
guessing, and neither has a hand-maintained list that a new table could be missing
from — the registry is the list, and a test asserts every table appears in it.

**Export** produces one JSON document per table, with per-table row counts. The
counts are the point: an export that silently missed a table is the failure worth
detecting, and it is only detectable against the registry that produced the list.
Four kinds of column never leave:

* pseudonymisation salts, which would make every analytics reference reversible;
* live token digests, which are capabilities rather than records;
* credential fingerprints, which are a confirmation oracle;
* Hermes session handles, which are a live conversation somebody could steer.

Each withheld column is *named* in the export's manifest rather than silently
dropped, so the customer receives a document that says what it does not contain.

**Deletion** refuses rather than partially complying. A live retention hold stops
the request with the hold's own authority quoted back; there is no "delete what we
can" path, because a half-deleted Organization satisfies neither the request nor
the obligation. Two scopes exist and they are genuinely different requests:
``OperationalContent`` removes conversations, drafts, sessions and saved
selections — the things ADR-0026 already gives a shorter lifetime; ``Everything``
also removes the commercial record.

What deletion never removes is the audit trail of the deletion itself, the
Organization row, or the platform's own record that the request happened. An
erasure nobody can prove happened is not a service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    DataLifecycleState,
    DeletionScope,
    Organization,
    OrganizationDataDeletion,
    OrganizationDataExport,
    OrganizationRetentionHold,
    RetentionBasis,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import CommercialError, NotFound
from realestate.domain.platform.authority import PlatformOperator, require_reason
from realestate.domain.platform.scoping import (
    CIRCULAR_POINTERS,
    ScopeKind,
    organization_scopes,
    qualified_name,
    scope_for,
)

logger = logging.getLogger(__name__)

#: Tables the export reads but deletion never empties, whatever the scope. The
#: Organization row itself survives because the audit trail references it; the
#: lifecycle records survive because they *are* the evidence the request was
#: honoured.
NEVER_DELETED = frozenset(
    {
        "organizations",
        "organization_data_exports",
        "organization_data_deletions",
        "organization_retention_holds",
        "audit_events",
    }
)


class DeletionBlocked(CommercialError):
    """A live retention hold forbids this deletion."""

    message = (
        "No se puede eliminar la información de esta organización: hay una "
        "retención vigente."
    )


class ExportFailed(CommercialError):
    """The export could not be written."""

    message = "No se pudo generar la exportación de la organización."


@dataclass(frozen=True)
class ExportOrganizationData:
    organization_id: uuid.UUID
    reason: str
    command_key: str


@dataclass(frozen=True)
class DeleteOrganizationData:
    organization_id: uuid.UUID
    scope: DeletionScope
    reason: str
    command_key: str


@dataclass(frozen=True)
class RecordRetentionHold:
    organization_id: uuid.UUID
    basis: RetentionBasis
    authority: str
    description: str
    #: When the obligation lapses, if it does. ``None`` means a human has to
    #: release it, which is the right default for a legal duty nobody has dated.
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ExportResult:
    export_id: uuid.UUID
    organization_id: uuid.UUID
    artifact_path: str
    checksum: str
    byte_size: int
    row_counts: dict[str, int] = field(default_factory=dict)
    withheld: dict[str, list[str]] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return sum(self.row_counts.values())

    @property
    def tables(self) -> int:
        return len(self.row_counts)


@dataclass(frozen=True)
class DeletionResult:
    deletion_id: uuid.UUID
    organization_id: uuid.UUID
    scope: DeletionScope
    state: DataLifecycleState
    deleted_counts: dict[str, int] = field(default_factory=dict)
    retained_counts: dict[str, int] = field(default_factory=dict)
    blocked_reason: str | None = None

    @property
    def deleted(self) -> int:
        return sum(self.deleted_counts.values())

    @property
    def retained(self) -> int:
        return sum(self.retained_counts.values())


class OrganizationDataLifecycle:
    """Export and delete one Organization's data, bounded by retention.

    Hides: the scoping registry walk, the analytics schema's qualified names, the
    withheld columns, the reverse dependency order deletion needs, and the
    retention check that refuses rather than partially complying.
    """

    def __init__(self, session: AsyncSession, *, root: Path | None = None) -> None:
        self._session = session
        # Where export artifacts land. Defaulted rather than required so a test
        # can point it at a temporary directory and the production path stays one
        # configured value.
        self._root = root or Path("var/organization-exports")

    # -- Export ------------------------------------------------------------

    async def export(
        self,
        operator: PlatformOperator,
        command: ExportOrganizationData,
        *,
        at: datetime | None = None,
    ) -> ExportResult:
        """Write everything one Organization owns to one artifact. Commits.

        Idempotent on ``command_key``: a resubmitted request returns the artifact
        the first one produced rather than writing a second copy of somebody's
        entire customer base to disk.
        """
        reason = require_reason(command.reason)
        moment = at or utc_now()
        organization = await self._session.get(Organization, command.organization_id)
        if organization is None:
            raise NotFound("No encontramos esa organización.")

        replay = await self._session.scalar(
            select(OrganizationDataExport)
            .where(
                OrganizationDataExport.organization_id == command.organization_id
            )
            .where(OrganizationDataExport.command_key == command.command_key)
        )
        if replay is not None and replay.state == DataLifecycleState.COMPLETED.value:
            return ExportResult(
                export_id=replay.id,
                organization_id=replay.organization_id,
                artifact_path=replay.artifact_path or "",
                checksum=replay.checksum or "",
                byte_size=replay.byte_size or 0,
                row_counts=dict(replay.row_counts),
                withheld={
                    table: list(columns)
                    for table, columns in dict(replay.withheld).items()
                },
            )

        record = replay or OrganizationDataExport(
            organization_id=command.organization_id,
            command_key=command.command_key,
            state=DataLifecycleState.REQUESTED.value,
            requested_by=operator.label,
            reason=reason,
            requested_at=moment,
        )
        if replay is None:
            self._session.add(record)
            await self._session.flush()

        tables: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        withheld: dict[str, list[str]] = {}
        for scope in organization_scopes():
            column = scope.scope_column
            assert column is not None  # organization_scopes filters on this
            name = qualified_name(scope.table)
            rows = await self._rows(name, column, command.organization_id)
            if scope.withheld:
                withheld[scope.table] = list(scope.withheld)
                rows = [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in scope.withheld
                    }
                    for row in rows
                ]
            tables[scope.table] = rows
            counts[scope.table] = len(rows)

        document = {
            "organization": {
                "id": str(organization.id),
                "slug": organization.slug,
                "display_name": organization.display_name,
                "status": organization.status,
            },
            "export": {
                "requested_by": operator.label,
                "requested_at": moment.isoformat(),
                "reason": reason,
                "tables": len(counts),
                "rows": sum(counts.values()),
                # Named, not silently dropped. A customer receiving this is told
                # exactly what it does not contain and why.
                "withheld_columns": withheld,
                "withheld_explanation": (
                    "Se omiten sales de pseudonimización, huellas de "
                    "credenciales, digests de tokens vigentes y manejadores de "
                    "sesión del modelo. Incluirlos permitiría revertir la "
                    "pseudonimización o reutilizar un acceso vigente."
                ),
            },
            "row_counts": counts,
            "data": tables,
        }
        payload = json.dumps(
            document, ensure_ascii=False, indent=2, sort_keys=True, default=str
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        artifact = self._root / f"{organization.slug}-{digest[:16]}.json"
        try:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(payload)
        except OSError as exc:
            record.state = DataLifecycleState.FAILED.value
            record.failure = str(exc)
            await self._session.commit()
            raise ExportFailed() from exc

        record.state = DataLifecycleState.COMPLETED.value
        record.artifact_path = str(artifact)
        record.checksum = digest
        record.byte_size = len(payload)
        record.row_counts = counts
        record.withheld = withheld
        record.completed_at = moment

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="ExportOrganizationData",
            subject_type="Organization",
            subject_id=str(command.organization_id),
            details={
                "tables": len(counts),
                "rows": sum(counts.values()),
                "checksum": digest,
                "withheld": withheld,
                "reason": reason,
            },
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "Exported Organization %s: %d table(s), %d row(s), %d bytes",
            organization.slug,
            len(counts),
            sum(counts.values()),
            len(payload),
        )
        return ExportResult(
            export_id=record.id,
            organization_id=command.organization_id,
            artifact_path=str(artifact),
            checksum=digest,
            byte_size=len(payload),
            row_counts=counts,
            withheld=withheld,
        )

    # -- Deletion ----------------------------------------------------------

    async def delete(
        self,
        operator: PlatformOperator,
        command: DeleteOrganizationData,
        *,
        at: datetime | None = None,
    ) -> DeletionResult:
        """Remove one Organization's data, or refuse and say why. Commits.

        Rows are deleted in the reverse of the metadata's dependency order, which
        is derived rather than written down: a hand-maintained order is wrong the
        first time somebody adds a table, and the symptom is a deletion that fails
        halfway through with a foreign-key error and a customer waiting.
        """
        reason = require_reason(command.reason)
        moment = at or utc_now()
        organization = await self._session.get(Organization, command.organization_id)
        if organization is None:
            raise NotFound("No encontramos esa organización.")

        replay = await self._session.scalar(
            select(OrganizationDataDeletion)
            .where(
                OrganizationDataDeletion.organization_id == command.organization_id
            )
            .where(OrganizationDataDeletion.command_key == command.command_key)
        )
        if replay is not None and replay.state in (
            DataLifecycleState.COMPLETED.value,
            DataLifecycleState.BLOCKED.value,
        ):
            return DeletionResult(
                deletion_id=replay.id,
                organization_id=replay.organization_id,
                scope=DeletionScope(replay.scope),
                state=DataLifecycleState(replay.state),
                deleted_counts=dict(replay.deleted_counts),
                retained_counts=dict(replay.retained_counts),
                blocked_reason=replay.blocked_reason,
            )

        record = replay or OrganizationDataDeletion(
            organization_id=command.organization_id,
            command_key=command.command_key,
            scope=command.scope.value,
            state=DataLifecycleState.REQUESTED.value,
            requested_by=operator.label,
            reason=reason,
            requested_at=moment,
        )
        if replay is None:
            self._session.add(record)
            await self._session.flush()

        holds = await self.live_holds(command.organization_id, at=moment)
        if holds:
            blocked = "; ".join(
                f"{hold.basis} — {hold.authority}: {hold.description}"
                for hold in holds
            )
            record.state = DataLifecycleState.BLOCKED.value
            record.blocked_reason = blocked
            record.completed_at = moment
            await record_audit(
                self._session,
                organization_id=command.organization_id,
                actor_type=operator.actor_type,
                actor_id=operator.label,
                action="BlockOrganizationDeletion",
                subject_type="Organization",
                subject_id=str(command.organization_id),
                details={
                    "scope": command.scope.value,
                    "holds": [str(hold.id) for hold in holds],
                    "reason": reason,
                },
                commit=False,
            )
            await self._session.commit()
            logger.warning(
                "Refused deletion for Organization %s: %s",
                organization.slug,
                blocked,
            )
            return DeletionResult(
                deletion_id=record.id,
                organization_id=command.organization_id,
                scope=command.scope,
                state=DataLifecycleState.BLOCKED,
                blocked_reason=blocked,
            )

        deleted: dict[str, int] = {}
        retained: dict[str, int] = {}
        # The one circular reference first. A dependency sort cannot break a
        # cycle, so ``properties.accepted_version_id`` is cleared before anything
        # is removed — otherwise the delete fails on the document versions with
        # half the Organization already gone.
        for table, column in CIRCULAR_POINTERS:
            if table in NEVER_DELETED:
                continue
            if command.scope is DeletionScope.OPERATIONAL_CONTENT and not (
                scope_for(table).content
            ):
                continue
            await self._session.execute(
                text(
                    f"UPDATE {qualified_name(table)} SET {column} = NULL "
                    "WHERE organization_id = :organization_id"
                ).bindparams(organization_id=command.organization_id)
            )
        # Reverse dependency order: children before the parents they reference.
        for scope in reversed(organization_scopes()):
            if scope.kind is ScopeKind.ORGANIZATION_ROOT:
                continue
            name = qualified_name(scope.table)
            if scope.table in NEVER_DELETED or (
                command.scope is DeletionScope.OPERATIONAL_CONTENT
                and not scope.content
            ):
                remaining = await self._count(
                    name, "organization_id", command.organization_id
                )
                if remaining:
                    retained[scope.table] = remaining
                continue
            removed = await self._delete_rows(
                name, "organization_id", command.organization_id
            )
            if removed:
                deleted[scope.table] = removed

        record.state = DataLifecycleState.COMPLETED.value
        record.deleted_counts = deleted
        record.retained_counts = retained
        record.completed_at = moment

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="DeleteOrganizationData",
            subject_type="Organization",
            subject_id=str(command.organization_id),
            details={
                "scope": command.scope.value,
                "deleted_rows": sum(deleted.values()),
                "deleted_tables": sorted(deleted),
                "retained_rows": sum(retained.values()),
                "retained_tables": sorted(retained),
                "reason": reason,
            },
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "Deleted %s data for Organization %s: %d row(s) across %d table(s)",
            command.scope.value,
            organization.slug,
            sum(deleted.values()),
            len(deleted),
        )
        return DeletionResult(
            deletion_id=record.id,
            organization_id=command.organization_id,
            scope=command.scope,
            state=DataLifecycleState.COMPLETED,
            deleted_counts=deleted,
            retained_counts=retained,
        )

    # -- Retention ---------------------------------------------------------

    async def record_hold(
        self,
        operator: PlatformOperator,
        command: RecordRetentionHold,
        *,
        at: datetime | None = None,
    ) -> OrganizationRetentionHold:
        """Record a reason this Organization's data may not be deleted. Commits."""
        description = require_reason(command.description)
        moment = at or utc_now()
        if not command.authority.strip():
            raise DeletionBlocked(
                "Una retención necesita nombrar la autoridad que la exige."
            )
        hold = OrganizationRetentionHold(
            organization_id=command.organization_id,
            basis=command.basis.value,
            authority=command.authority.strip(),
            description=description,
            recorded_by=operator.label,
            recorded_at=moment,
            expires_at=command.expires_at,
        )
        self._session.add(hold)
        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RecordRetentionHold",
            subject_type="Organization",
            subject_id=str(command.organization_id),
            details={
                "basis": command.basis.value,
                "authority": command.authority.strip(),
                "expires_at": (
                    command.expires_at.isoformat()
                    if command.expires_at is not None
                    else None
                ),
            },
            commit=False,
        )
        await self._session.commit()
        return hold

    async def release_hold(
        self,
        operator: PlatformOperator,
        *,
        hold_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> OrganizationRetentionHold:
        """End one hold. Commits. The row survives, closed rather than deleted."""
        explanation = require_reason(reason)
        moment = at or utc_now()
        hold = await self._session.get(
            OrganizationRetentionHold, hold_id, with_for_update=True
        )
        if hold is None:
            raise NotFound("No encontramos esa retención.")
        if hold.released_at is None:
            hold.released_at = moment
            hold.released_by = operator.label
            await record_audit(
                self._session,
                organization_id=hold.organization_id,
                actor_type=operator.actor_type,
                actor_id=operator.label,
                action="ReleaseRetentionHold",
                subject_type="Organization",
                subject_id=str(hold.organization_id),
                details={"hold_id": str(hold.id), "reason": explanation},
                commit=False,
            )
        await self._session.commit()
        return hold

    async def live_holds(
        self, organization_id: uuid.UUID, *, at: datetime | None = None
    ) -> list[OrganizationRetentionHold]:
        """Holds that currently forbid deletion.

        A hold with an expiry releases itself by lapsing; one without needs a
        human, which is the correct default for a legal duty nobody has dated.
        """
        moment = at or utc_now()
        rows = await self._session.scalars(
            select(OrganizationRetentionHold)
            .where(OrganizationRetentionHold.organization_id == organization_id)
            .where(OrganizationRetentionHold.released_at.is_(None))
            .order_by(OrganizationRetentionHold.recorded_at)
        )
        return [
            hold
            for hold in rows
            if hold.expires_at is None or moment < hold.expires_at
        ]

    async def exports(
        self, organization_id: uuid.UUID
    ) -> list[OrganizationDataExport]:
        rows = await self._session.scalars(
            select(OrganizationDataExport)
            .where(OrganizationDataExport.organization_id == organization_id)
            .order_by(OrganizationDataExport.requested_at.desc())
        )
        return list(rows)

    async def deletions(
        self, organization_id: uuid.UUID
    ) -> list[OrganizationDataDeletion]:
        rows = await self._session.scalars(
            select(OrganizationDataDeletion)
            .where(OrganizationDataDeletion.organization_id == organization_id)
            .order_by(OrganizationDataDeletion.requested_at.desc())
        )
        return list(rows)

    # -- internals ---------------------------------------------------------

    async def _rows(
        self, table: str, column: str, organization_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Every row of one table belonging to one Organization.

        Raw SQL because the export is *about the schema*: reflecting over mapped
        classes would mean the export knew a table only if somebody remembered to
        add it, which is exactly the failure the scoping registry removes. The
        table name comes from the registry, never from a caller, so there is no
        interpolation an input could reach.
        """
        result = await self._session.execute(
            text(f"SELECT * FROM {table} WHERE {column} = :organization_id").bindparams(
                organization_id=organization_id
            )
        )
        return [dict(row) for row in result.mappings()]

    async def _count(
        self, table: str, column: str, organization_id: uuid.UUID
    ) -> int:
        found = await self._session.scalar(
            text(
                f"SELECT count(*) FROM {table} WHERE {column} = :organization_id"
            ).bindparams(organization_id=organization_id)
        )
        return int(found or 0)

    async def _delete_rows(
        self, table: str, column: str, organization_id: uuid.UUID
    ) -> int:
        """Remove one table's rows for one Organization, returning the count.

        ``RETURNING`` rather than ``rowcount``: the count is what the deletion
        record reports back to the customer, and the async result object does not
        expose a typed row count.
        """
        result = await self._session.execute(
            text(
                f"DELETE FROM {table} WHERE {column} = :organization_id "
                "RETURNING 1"
            ).bindparams(organization_id=organization_id)
        )
        return len(result.all())
