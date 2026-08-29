"""A new Organization's existing records, dry-run first.

An inmobiliaria arriving on the platform has inventory already: a spreadsheet, an
EasyBroker account, a folder of PDFs. Importing it is the single most dangerous
routine in an onboarding, for a reason that is not obvious — the danger is not
losing records, it is *accepting* them. An import that silently creates 412
Properties with plausible-looking prices produces a catalog nobody reviewed, on a
public site, under a brand that is not ours.

So the shape is:

**Dry run first, always.** A dry run reads the same source, applies the same
validation and records the same per-record findings — and creates nothing. The
operator and the customer look at the findings together, and the numbers they
agree on are the numbers the apply has to match. That comparison only works
because a dry run and an apply are the *same plan* with a mode, rather than two
code paths that drift.

**Every record gets a finding.** Accepted, duplicate, invalid or skipped, one row
each, with the source's own identifier on it. A summary of counts alone cannot
answer "which twelve were rejected", which is the only question the customer has.

**Rollback removes exactly what the apply created.** Each accepted finding stores
the identifier of the record it made, so undoing is a list of primary keys rather
than "delete everything recent" — which is not a rollback, it is a second
incident.

**Provenance survives.** Where the records came from, when, and with what
checksum, on the run; the source's own reference on every finding. Six months
later "where did this Property come from" has an answer that is not somebody's
memory (ADR-0055).

What lands is deliberately conservative: a Property with reviewed physical facts
in the ``Pending`` review state, and nothing else. No Listing, no Offer, no
publication, no media, no price treated as authority. Those are decisions the
catalog module already requires a human to make, and an import that made them
would be exactly the unreviewed catalog above.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    FactsReviewState,
    ImportFindingKind,
    ImportMode,
    ImportState,
    Organization,
    OrganizationImportFinding,
    OrganizationImportRun,
    OrganizationStatus,
    Property,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import CommercialError, NotFound
from realestate.domain.platform.authority import PlatformOperator, require_reason
from realestate.domain.property_document import (
    PROPERTY_KEY_PATTERN,
    PROPERTY_TYPES,
    normalize_name,
)

logger = logging.getLogger(__name__)

#: The most records one run will consider. Not a limitation of the code — a
#: limitation of what a human can review in one sitting. An import bigger than
#: this is several runs, each with its own findings somebody actually read.
MAX_RECORDS = 2_000


class ImportRefused(CommercialError):
    """The run cannot proceed as asked."""

    message = "No se puede importar con esos datos."


@dataclass(frozen=True)
class IncomingProperty:
    """One physical Property as the source describes it.

    Deliberately narrow. The source's price, operation, publication state and
    photographs are *not* fields here, because accepting them would be accepting
    commercial authority from a spreadsheet.
    """

    #: The source's own identifier, kept as provenance whatever happens.
    source_reference: str
    property_key: str
    name: str
    property_type: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    visit_address: str | None = None


@dataclass(frozen=True)
class ImportPlan:
    """One source, described well enough to be auditable."""

    organization_id: uuid.UUID
    #: Where this came from, in the operator's words: a file name, an account, a
    #: date. Required, because "imported" with no origin is not provenance.
    source: str
    records: Sequence[IncomingProperty]
    reason: str
    command_key: str
    mode: ImportMode = ImportMode.DRY_RUN


@dataclass(frozen=True)
class Finding:
    """What the importer decided about one incoming record."""

    ordinal: int
    kind: ImportFindingKind
    entity: str
    source_reference: str
    detail: str | None = None
    created_record_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ImportReport:
    """One run's outcome, at the grain a human reviews."""

    run_id: uuid.UUID
    organization_id: uuid.UUID
    mode: ImportMode
    state: ImportState
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    refusal: str | None = None

    def count(self, kind: ImportFindingKind) -> int:
        return sum(1 for item in self.findings if item.kind is kind)

    @property
    def summary(self) -> dict[str, int]:
        return {kind.value: self.count(kind) for kind in ImportFindingKind}

    @property
    def accepted(self) -> int:
        return self.count(ImportFindingKind.ACCEPTED)

    def matches(self, other: ImportReport) -> bool:
        """Whether a dry run and an apply reached the same conclusions.

        The whole reason both share one code path. Compared on the per-record
        decisions rather than on the totals, because two runs can agree on "412
        accepted" while disagreeing about *which* 412.
        """
        return [
            (item.source_reference, item.kind) for item in self.findings
        ] == [(item.source_reference, item.kind) for item in other.findings]


def checksum_of(records: Sequence[IncomingProperty]) -> str:
    """A digest of exactly what was read, so a re-read can be proved identical."""
    payload = json.dumps(
        [
            {
                "source_reference": item.source_reference,
                "property_key": item.property_key,
                "name": item.name,
                "property_type": item.property_type,
                "facts": dict(item.facts),
            }
            for item in records
        ],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class OrganizationImport:
    """Plan, apply and roll back one Organization's initial migration.

    Hides: the run and finding rows, the duplicate detection, what "valid" means
    for an incoming Property, and the fact that rollback is a list of identifiers
    rather than a time window.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def plan(
        self, operator: PlatformOperator, request: ImportPlan, *, at: datetime | None = None
    ) -> ImportReport:
        """Decide about every record without creating anything. Commits.

        The findings are stored, not just returned: the conversation with the
        customer happens after the call, and a dry run whose output lived only in
        a response body could not be compared with the apply that followed it.
        """
        return await self._run(
            operator, request, mode=ImportMode.DRY_RUN, at=at
        )

    async def apply(
        self, operator: PlatformOperator, request: ImportPlan, *, at: datetime | None = None
    ) -> ImportReport:
        """Create what the plan accepted. Commits.

        Requires a completed dry run over the *same* source checksum. Not
        bureaucracy: without it, "the numbers we agreed on" has no referent, and
        the first time anybody notices is when the public site shows a Property
        nobody reviewed.
        """
        moment = at or utc_now()
        digest = checksum_of(request.records)
        previous = await self._session.scalar(
            select(OrganizationImportRun)
            .where(OrganizationImportRun.organization_id == request.organization_id)
            .where(OrganizationImportRun.mode == ImportMode.DRY_RUN.value)
            .where(OrganizationImportRun.state == ImportState.PLANNED.value)
            .where(
                OrganizationImportRun.provenance["checksum"].as_string() == digest
            )
            .order_by(OrganizationImportRun.planned_at.desc())
            .limit(1)
        )
        if previous is None:
            raise ImportRefused(
                "Antes de aplicar una importación hay que ejecutar una prueba "
                "en seco de exactamente los mismos registros y revisar sus "
                "resultados."
            )
        return await self._run(
            operator, request, mode=ImportMode.APPLY, at=moment, dry_run_id=previous.id
        )

    async def roll_back(
        self,
        operator: PlatformOperator,
        *,
        run_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> ImportReport:
        """Remove exactly the records one applied run created. Commits.

        A Property another record already references — an appointment, a
        Listing — is left in place and reported rather than force-deleted. The
        foreign keys would refuse anyway, and a rollback that cascaded through a
        confirmed visit would be doing damage to undo an inconvenience.
        """
        explanation = require_reason(reason)
        moment = at or utc_now()
        run = await self._session.get(
            OrganizationImportRun, run_id, with_for_update=True
        )
        if run is None:
            raise NotFound("No encontramos esa importación.")
        if run.mode != ImportMode.APPLY.value:
            raise ImportRefused("Una prueba en seco no creó nada que revertir.")
        if run.state == ImportState.ROLLED_BACK.value:
            return await self._report(run)

        findings = list(
            await self._session.scalars(
                select(OrganizationImportFinding)
                .where(OrganizationImportFinding.run_id == run_id)
                .where(
                    OrganizationImportFinding.kind
                    == ImportFindingKind.ACCEPTED.value
                )
                .order_by(OrganizationImportFinding.ordinal.desc())
            )
        )
        removed = 0
        retained: list[str] = []
        for finding in findings:
            if finding.created_record_id is None:
                continue
            row = await self._session.get(Property, finding.created_record_id)
            if row is None:
                continue
            try:
                async with self._session.begin_nested():
                    await self._session.delete(row)
                    await self._session.flush()
            except Exception:  # noqa: BLE001 - reported, not swallowed
                retained.append(finding.source_reference)
                continue
            removed += 1
            finding.detail = (
                f"Revertido el {moment.date().isoformat()}: {explanation}"
            )
            finding.created_record_id = None

        run.state = ImportState.ROLLED_BACK.value
        run.rolled_back_at = moment
        run.summary = {
            **dict(run.summary),
            "rolled_back": removed,
            "retained_on_rollback": retained,
        }
        await record_audit(
            self._session,
            organization_id=run.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RollBackOrganizationImport",
            subject_type="OrganizationImportRun",
            subject_id=str(run.id),
            details={
                "removed": removed,
                "retained": retained,
                "reason": explanation,
            },
            commit=False,
        )
        await self._session.commit()
        if retained:
            logger.warning(
                "Import rollback for run %s left %d record(s) in place because "
                "other records reference them: %s",
                run.id,
                len(retained),
                retained,
            )
        return await self._report(run)

    async def runs(
        self, organization_id: uuid.UUID
    ) -> list[OrganizationImportRun]:
        rows = await self._session.scalars(
            select(OrganizationImportRun)
            .where(OrganizationImportRun.organization_id == organization_id)
            .order_by(OrganizationImportRun.planned_at.desc())
        )
        return list(rows)

    async def report(self, run_id: uuid.UUID) -> ImportReport:
        run = await self._session.get(OrganizationImportRun, run_id)
        if run is None:
            raise NotFound("No encontramos esa importación.")
        return await self._report(run)

    # -- internals ---------------------------------------------------------

    async def _run(
        self,
        operator: PlatformOperator,
        request: ImportPlan,
        *,
        mode: ImportMode,
        at: datetime | None,
        dry_run_id: uuid.UUID | None = None,
    ) -> ImportReport:
        reason = require_reason(request.reason)
        moment = at or utc_now()
        if not request.source.strip():
            raise ImportRefused(
                "Una importación necesita nombrar su origen: el archivo, la "
                "cuenta o la fecha de la que provienen los registros."
            )
        if not request.records:
            raise ImportRefused("No hay registros que importar.")
        if len(request.records) > MAX_RECORDS:
            raise ImportRefused(
                f"Una importación admite hasta {MAX_RECORDS} registros por "
                "corrida. Divídela para que alguien pueda revisar los "
                "resultados."
            )
        organization = await self._session.get(Organization, request.organization_id)
        if organization is None:
            raise NotFound("No encontramos esa organización.")
        if organization.status == OrganizationStatus.DEPROVISIONED.value:
            raise ImportRefused(
                "No se importa información a una organización dada de baja."
            )

        replay = await self._session.scalar(
            select(OrganizationImportRun)
            .where(OrganizationImportRun.organization_id == request.organization_id)
            .where(OrganizationImportRun.command_key == request.command_key)
        )
        if replay is not None:
            return await self._report(replay)

        digest = checksum_of(request.records)
        run = OrganizationImportRun(
            organization_id=request.organization_id,
            command_key=request.command_key,
            mode=mode.value,
            state=ImportState.PLANNED.value,
            provenance={
                "source": request.source.strip(),
                "checksum": digest,
                "records": len(request.records),
                "read_at": moment.isoformat(),
                "dry_run_id": str(dry_run_id) if dry_run_id is not None else None,
            },
            requested_by=operator.label,
            planned_at=moment,
        )
        self._session.add(run)
        await self._session.flush()

        # Read once: every incoming key is checked against what the Organization
        # already has *and* against the keys earlier records in this same run
        # claimed, because a source duplicating a key inside one file is the
        # common case rather than the exotic one.
        existing_keys = {
            row[0]
            for row in await self._session.execute(
                select(Property.property_key).where(
                    Property.organization_id == request.organization_id
                )
            )
        }
        claimed: set[str] = set()

        findings: list[Finding] = []
        for ordinal, record in enumerate(request.records, start=1):
            problem = _validate(record)
            if problem is not None:
                findings.append(
                    Finding(
                        ordinal=ordinal,
                        kind=ImportFindingKind.INVALID,
                        entity="Property",
                        source_reference=record.source_reference,
                        detail=problem,
                    )
                )
                continue
            key = record.property_key.strip()
            if key in existing_keys or key in claimed:
                findings.append(
                    Finding(
                        ordinal=ordinal,
                        kind=ImportFindingKind.DUPLICATE,
                        entity="Property",
                        source_reference=record.source_reference,
                        detail=(
                            f"La organización ya tiene una propiedad con la "
                            f"clave «{key}»."
                        ),
                    )
                )
                continue
            claimed.add(key)
            created_id: uuid.UUID | None = None
            if mode is ImportMode.APPLY:
                created_id = await self._create(
                    request.organization_id, record, moment, run.id
                )
            findings.append(
                Finding(
                    ordinal=ordinal,
                    kind=ImportFindingKind.ACCEPTED,
                    entity="Property",
                    source_reference=record.source_reference,
                    detail=(
                        "Se creará como propiedad física con hechos por revisar."
                        if mode is ImportMode.DRY_RUN
                        else "Creada como propiedad física con hechos por revisar."
                    ),
                    created_record_id=created_id,
                )
            )

        for finding in findings:
            self._session.add(
                OrganizationImportFinding(
                    run_id=run.id,
                    organization_id=request.organization_id,
                    ordinal=finding.ordinal,
                    kind=finding.kind.value,
                    entity=finding.entity,
                    source_reference=finding.source_reference[:200],
                    detail=finding.detail,
                    created_record_id=finding.created_record_id,
                )
            )

        summary = {kind.value: 0 for kind in ImportFindingKind}
        for finding in findings:
            summary[finding.kind.value] += 1
        run.summary = summary
        if mode is ImportMode.APPLY:
            run.state = ImportState.APPLIED.value
            run.applied_at = moment

        await record_audit(
            self._session,
            organization_id=request.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action=(
                "PlanOrganizationImport"
                if mode is ImportMode.DRY_RUN
                else "ApplyOrganizationImport"
            ),
            subject_type="OrganizationImportRun",
            subject_id=str(run.id),
            details={
                "mode": mode.value,
                "source": request.source.strip(),
                "checksum": digest,
                "summary": summary,
                "reason": reason,
            },
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "Import %s for Organization %s: %s",
            mode.value,
            organization.slug,
            summary,
        )
        return ImportReport(
            run_id=run.id,
            organization_id=request.organization_id,
            mode=mode,
            state=ImportState(run.state),
            findings=tuple(findings),
            provenance=dict(run.provenance),
        )

    async def _create(
        self,
        organization_id: uuid.UUID,
        record: IncomingProperty,
        moment: datetime,
        run_id: uuid.UUID,
    ) -> uuid.UUID:
        """One physical Property, and nothing more.

        ``facts_review_state`` is ``Pending`` and the provenance names the run.
        An imported Property therefore cannot be published, recommended or
        scheduled until an Administrator reviews its facts — which is the
        existing catalog rule, not a special case for imports.
        """
        row = Property(
            organization_id=organization_id,
            property_key=record.property_key.strip(),
            name=record.name.strip(),
            normalized_name=normalize_name(record.name),
            status=PropertyStatus.ACTIVE.value,
            property_type=record.property_type,
            physical_facts=dict(record.facts),
            facts_review_state=FactsReviewState.PENDING.value,
            provenance={
                "origin": "OrganizationImport",
                "import_run_id": str(run_id),
                "source_reference": record.source_reference,
                "imported_at": moment.isoformat(),
            },
            visit_address=(record.visit_address or "").strip() or None,
            created_at=moment,
            updated_at=moment,
        )
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def _report(self, run: OrganizationImportRun) -> ImportReport:
        rows = await self._session.scalars(
            select(OrganizationImportFinding)
            .where(OrganizationImportFinding.run_id == run.id)
            .order_by(OrganizationImportFinding.ordinal)
        )
        return ImportReport(
            run_id=run.id,
            organization_id=run.organization_id,
            mode=ImportMode(run.mode),
            state=ImportState(run.state),
            findings=tuple(
                Finding(
                    ordinal=row.ordinal,
                    kind=ImportFindingKind(row.kind),
                    entity=row.entity,
                    source_reference=row.source_reference,
                    detail=row.detail,
                    created_record_id=row.created_record_id,
                )
                for row in rows
            ),
            provenance=dict(run.provenance),
            refusal=run.refusal,
        )


def _validate(record: IncomingProperty) -> str | None:
    """What makes an incoming Property unusable, or ``None``.

    Every rule here is one the catalog already enforces. Restating them at the
    boundary means the *report* says which twelve records were rejected and why,
    rather than the apply failing on the thirteenth and leaving twelve behind.
    """
    if not record.source_reference.strip():
        return "El registro no trae identificador de origen."
    key = record.property_key.strip()
    if not PROPERTY_KEY_PATTERN.match(key):
        return (
            "La clave de propiedad no tiene el formato aceptado "
            "(minúsculas, números y guiones)."
        )
    if not record.name.strip():
        return "Falta el nombre de la propiedad."
    if record.property_type not in PROPERTY_TYPES:
        return (
            "El tipo de propiedad no es uno de los aceptados: "
            + ", ".join(sorted(PROPERTY_TYPES))
            + "."
        )
    return None
