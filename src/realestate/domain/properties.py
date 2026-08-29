"""Property ingestion and documented-fact retrieval (ADR-0010, P-045…P-053).

This module is the Deterministic Backend's authority over Property identity,
accepted document versions, and status. It is the only place that decides what
the Sales Role may be told about a Property.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AgentRole,
    FactsReviewState,
    Property,
    PropertyDocumentVersion,
    PropertyInactiveReason,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.property_document import (
    PropertyDocument,
    ValidationError,
    normalize_name,
    split_front_matter,
    validate_upload,
)

# The accepted Stage 0 inventory cap (P-066). Enforced at ingestion so the
# administrative overview can never exceed it.
MAX_PROPERTIES = 10


@dataclass(frozen=True)
class AcceptedUpload:
    property_key: str
    name: str
    status: str
    version: int
    checksum: str
    created: bool

    @property
    def summary(self) -> str:
        action = "created" if self.created else "replaced"
        return (
            f"{self.name} ({self.property_key}) {action}: version {self.version}, "
            f"status {self.status}"
        )


class ArtifactStore:
    """Immutable content-addressed storage for accepted documents (P-050).

    The artifact is written *before* the database transaction opens. If the
    transaction then fails, the orphan is unreferenced, invisible to the Agent,
    and safe for later cleanup.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, content: bytes) -> tuple[str, Path]:
        checksum = hashlib.sha256(content).hexdigest()
        path = self._root / checksum[:2] / f"{checksum}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Content-addressed, so an existing file already holds these exact
            # bytes. Write via a temporary name so a reader never sees a partial
            # artifact.
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
        return checksum, path

    def read(self, path: str) -> bytes | None:
        artifact = Path(path)
        if not artifact.is_file():
            return None
        return artifact.read_bytes()


class CatalogStore:
    """Mutable public-safe current copies under ``src/properties``.

    This store is an administrative projection, not runtime truth. Every
    accepted version is still immutable in ``ArtifactStore`` and selected by
    PostgreSQL.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def replace(self, property_key: str, content: bytes) -> bytes | None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{property_key}.md"
        previous = path.read_bytes() if path.is_file() else None
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        return previous

    def restore(self, property_key: str, previous: bytes | None) -> None:
        path = self._root / f"{property_key}.md"
        if previous is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(previous)
        temporary.replace(path)

    def read(self, property_key: str) -> bytes | None:
        path = self._root / f"{property_key}.md"
        return path.read_bytes() if path.is_file() else None


def customer_availability_message(reason: str | None) -> str:
    """Customer-safe Spanish response for an unavailable Property."""
    return {
        PropertyInactiveReason.SOLD.value: "La propiedad ya fue vendida.",
        PropertyInactiveReason.RENTED.value: "La propiedad ya fue rentada.",
        PropertyInactiveReason.RESERVED.value: (
            "La propiedad está reservada y no está disponible por el momento."
        ),
    }.get(reason or "", "La propiedad no está disponible por el momento.")


async def resolve_property(
    session: AsyncSession,
    reference: str | None,
    organization_id: uuid.UUID,
) -> Property | None:
    """The Property a model-supplied *reference* names, inside one Organization.

    A readable key ('casa-roble') or the exact name ('Casa Roble'), compared by
    the P-048 normalisation. This is the one place that rule lives: the
    appointment and administrative surfaces resolve the same reference the same
    way, and neither needs the ingestion service to do it.

    ``organization_id`` is required since Stage 9 and used to have an optional
    "unscoped" mode. A readable key is guessable, so an unscoped resolution let
    a caller reach another Organization's Property by typing its name
    (ADR-0050).
    """
    candidate = (reference or "").strip()
    if not candidate:
        return None

    by_key = (
        await session.execute(
            select(Property)
            .where(Property.organization_id == organization_id)
            .where(Property.property_key == candidate)
        )
    ).scalar_one_or_none()
    if by_key is not None:
        return by_key

    by_name_query = (
        select(Property)
        .where(Property.organization_id == organization_id)
        .where(Property.normalized_name == normalize_name(candidate))
    )
    matches = list(await session.scalars(by_name_query.limit(2)))
    # Similar names are evidence to investigate, never permission to merge or
    # guess a physical identity. A key remains unambiguous.
    return matches[0] if len(matches) == 1 else None


async def accepted_version(
    session: AsyncSession, prop: Property
) -> PropertyDocumentVersion | None:
    """The document version a Property currently accepts, or None.

    Spelled once here for the same reason as ``resolve_property``: the
    retrieval, administrative, and manual-editing surfaces all need it, and
    "``accepted_version_id`` is the pointer" is a domain rule rather than
    something each caller should re-derive.
    """
    if prop.accepted_version_id is None:
        return None
    return await session.get(PropertyDocumentVersion, prop.accepted_version_id)


class PropertyService:
    """The legacy Property Document path, scoped to one Organization.

    ``organization_id`` is a constructor argument and has no default. It used to
    be resolved inside the service from the one Organization that existed, with a
    comment saying a selector would arrive later. This is that selector: every
    caller now names the Organization it is acting for, because an upload surface
    that guesses is a surface that files a second brokerage's inventory under the
    first one's (ADR-0050).
    """

    def __init__(
        self,
        session: AsyncSession,
        artifacts: ArtifactStore,
        catalog: CatalogStore | None = None,
        *,
        organization_id: uuid.UUID,
    ) -> None:
        self._session = session
        self._artifacts = artifacts
        self._catalog = catalog
        self._organization = organization_id

    # -- Ingestion --------------------------------------------------------

    async def accept_upload(
        self,
        filename: str,
        content: bytes,
        actor_id: str,
        *,
        actor_type: str = "Developer",
        create_only: bool = False,
        expected_property_key: str | None = None,
        visit_address: str | None = None,
    ) -> AcceptedUpload:
        """Validate and atomically accept one Property Document.

        Raises ``ValidationError`` without persisting anything if the document
        is invalid or would collide. A valid first upload creates the Property
        as ``Active``; a valid replacement preserves the existing status (P-046).

        ``visit_address`` is private operational data the document never
        carries. ``None`` means the caller is not speaking about it, so a
        replacement leaves any stored address untouched; a string sets it, and
        an empty one clears it.
        """
        document = validate_upload(filename, content)

        if expected_property_key and document.property_key != expected_property_key:
            raise ValidationError(
                ["property_id is immutable and cannot be changed while editing."]
            )

        existing = await self._by_key(document.property_key)
        if create_only and existing is not None:
            raise ValidationError(
                [
                    f"property_id: {document.property_key!r} already exists. "
                    "Choose a different name/key instead of adding a numeric suffix."
                ]
            )
        if existing is None:
            await self._reject_inventory_overflow()

        # Artifact first, then the transaction (P-050).
        checksum, artifact_path = self._artifacts.write(document.raw_bytes)
        previous_catalog: bytes | None = None
        if self._catalog is not None:
            previous_catalog = self._catalog.replace(
                document.property_key, document.raw_bytes
            )

        try:
            if existing is None:
                accepted = await self._create_property(
                    document,
                    checksum,
                    artifact_path,
                    actor_id=actor_id,
                    visit_address=visit_address,
                )
            else:
                accepted = await self._add_version(
                    existing,
                    document,
                    checksum,
                    artifact_path,
                    visit_address=visit_address,
                )
            await self._session.commit()
        except Exception as exc:
            # One compensation for every failure: the catalog copy is written
            # before the transaction, so whatever went wrong it has to go back.
            await self._session.rollback()
            if self._catalog is not None:
                self._catalog.restore(document.property_key, previous_catalog)
            if isinstance(exc, IntegrityError):
                raise ValidationError(
                    [
                        "The upload conflicted with an existing Property and was "
                        "rejected. No accepted document or status was changed."
                    ]
                ) from exc
            raise

        await self._audit(
            # Read before the audit rather than resolved again: the acceptance
            # transaction has already committed, and asking the directory a
            # second time would be a second chance to name a different one.
            organization_id=self._organization,
            actor_type=actor_type,
            actor_id=actor_id,
            action="PropertyDocumentAccepted",
            subject_id=accepted.property_key,
            details={
                "version": accepted.version,
                "checksum": accepted.checksum,
                "created": accepted.created,
                "status": accepted.status,
                "name": accepted.name,
            },
        )
        return accepted

    async def _by_key(self, property_key: str) -> Property | None:
        """This Organization's Property with that key, if it has one.

        Scoped since Stage 9. Unscoped, a second Organization uploading a
        document whose key the first one already used was treated as a
        *replacement* of the first one's Property — a cross-organization write
        that reported success (ADR-0050).
        """
        result = await self._session.execute(
            select(Property)
            .where(Property.organization_id == self._organization)
            .where(Property.property_key == property_key)
        )
        return result.scalar_one_or_none()

    async def _reject_inventory_overflow(self) -> None:
        """The Stage 0 inventory ceiling, counted per Organization.

        Counted across the whole table it would have let one brokerage's
        inventory exhaust another's allowance.
        """
        count = (
            await self._session.execute(
                select(func.count())
                .select_from(Property)
                .where(Property.organization_id == self._organization)
            )
        ).scalar_one()
        if count >= MAX_PROPERTIES:
            raise ValidationError(
                [
                    f"Stage 0 accepts at most {MAX_PROPERTIES} Properties and "
                    f"{count} already exist."
                ]
            )

    async def _create_property(
        self,
        document: PropertyDocument,
        checksum: str,
        artifact_path: Path,
        *,
        actor_id: str,
        visit_address: str | None,
    ) -> AcceptedUpload:
        prop = Property(
            organization_id=self._organization,
            property_key=document.property_key,
            name=document.name,
            normalized_name=document.normalized_name,
            # A valid first upload creates the Property as Active (P-045).
            status=PropertyStatus.ACTIVE.value,
            inactive_reason=None,
            visit_address=(visit_address or "").strip() or None,
            property_type=str(document.metadata["property_type"]),
            physical_facts=_physical_facts(document.metadata),
            facts_review_state=FactsReviewState.APPROVED.value,
            provenance={"kind": "PropertyDocument", "checksum": checksum},
        )
        self._session.add(prop)
        await self._session.flush()  # INSERT ... RETURNING id

        version = self._new_version(prop, document, 1, checksum, artifact_path)
        self._session.add(version)
        await self._session.flush()
        prop.accepted_version_id = version.id

        # Stage 4 compatibility cut: the accepted document is an input.  Its
        # initial Offer is copied once into Product's catalog; subsequent
        # commercial edits happen only through OfferManagement.
        from realestate.domain.catalog.administration import (
            CatalogAdministration,
            ImportLegacyDocument,
        )
        from realestate.domain.commercial.actors import Actor

        await CatalogAdministration(self._session).record(
            Actor.product(prop.organization_id, f"PropertyDocument:{actor_id}"),
            ImportLegacyDocument(
                property_uuid=prop.id,
                document_version_id=version.id,
                metadata=document.metadata,
                command_key=f"legacy-catalog:{version.id}",
            ),
        )

        return AcceptedUpload(
            property_key=prop.property_key,
            name=prop.name,
            status=prop.status,
            version=1,
            checksum=checksum,
            created=True,
        )

    async def _add_version(
        self,
        prop: Property,
        document: PropertyDocument,
        checksum: str,
        artifact_path: Path,
        *,
        visit_address: str | None,
    ) -> AcceptedUpload:
        latest = (
            await self._session.execute(
                select(PropertyDocumentVersion.version)
                .where(PropertyDocumentVersion.property_uuid == prop.id)
                .order_by(PropertyDocumentVersion.version.desc())
                .limit(1)
            )
        ).scalar_one()

        version = self._new_version(prop, document, latest + 1, checksum, artifact_path)
        self._session.add(version)
        await self._session.flush()

        # A replacement moves the accepted pointer and the Lead-facing name but
        # never the status (P-046): updating an Inactive Property cannot
        # reactivate it.
        prop.accepted_version_id = version.id
        prop.name = document.name
        prop.normalized_name = document.normalized_name
        prop.property_type = str(document.metadata["property_type"])
        prop.physical_facts = _physical_facts(document.metadata)
        prop.facts_review_state = FactsReviewState.APPROVED.value
        prop.provenance = {
            "kind": "PropertyDocument",
            "version_id": str(version.id),
            "checksum": checksum,
        }
        if visit_address is not None:
            prop.visit_address = visit_address.strip() or None

        return AcceptedUpload(
            property_key=prop.property_key,
            name=prop.name,
            status=prop.status,
            version=version.version,
            checksum=checksum,
            created=False,
        )

    def _new_version(
        self,
        prop: Property,
        document: PropertyDocument,
        number: int,
        checksum: str,
        artifact_path: Path,
    ) -> PropertyDocumentVersion:
        return PropertyDocumentVersion(
            # Read from the Property rather than resolved again: an accepted
            # document version belongs to whichever Organization owns the
            # Property, and the composite foreign key enforces exactly that.
            organization_id=prop.organization_id,
            property_uuid=prop.id,
            version=number,
            checksum=checksum,
            artifact_path=str(artifact_path),
            byte_size=len(document.raw_bytes),
            document_metadata=document.metadata,
        )

    async def _audit(
        self,
        *,
        organization_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        subject_id: str,
        details: dict[str, Any],
        subject_type: str = "Property",
    ) -> None:
        await record_audit(
            self._session,
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            subject_id=subject_id,
            details=details,
            subject_type=subject_type,
        )

    # -- Retrieval --------------------------------------------------------

    async def get_property_information(
        self, reference: str, role: AgentRole, actor_id: str = ""
    ) -> dict[str, Any]:
        """Resolve `get_property_information` under role-aware policy (P-053).

        ``reference`` is a readable Property Key or the Lead-facing name. A
        database UUID is never accepted; it would simply fail to resolve.

        The request is audited before the answer is returned, so "did the Agent
        actually consult the document?" is a question the product can answer
        from its own records rather than from a model transcript.
        """
        result = await self._property_information(reference, role)
        await self._audit(
            organization_id=self._organization,
            actor_type=role.value,
            actor_id=actor_id or "unknown-session",
            action="PropertyInformationRequested",
            subject_id=reference,
            details={"result": result["result"], "role": role.value},
        )
        return result

    async def _property_information(self, reference: str, role: AgentRole) -> dict[str, Any]:
        prop = await self._resolve(reference)
        if prop is None:
            return {"result": "not_found"}

        authorized = None
        if role is AgentRole.SALES:
            # Temporary fail-closed compatibility while legacy status remains
            # a read projection. Production writes update both in one
            # transaction; disagreement must never broaden disclosure.
            if prop.status == PropertyStatus.INACTIVE.value:
                return {
                    "result": "unavailable",
                    "property_id": prop.property_key,
                    "name": prop.name,
                    "status": prop.status,
                    "customer_message": customer_availability_message(
                        prop.inactive_reason
                    ),
                }
            # The Property Document is provenance, not commercial authority.
            # Resolve the exact source Listing and make customer disclosure pass
            # the same eligibility gate used by every other catalog projection.
            from realestate.domain.catalog.eligibility import EligibilityPurpose
            from realestate.domain.catalog.projection import (
                AuthorizedListingQuery,
                CatalogProjection,
                ListingNotEligible,
            )
            from realestate.domain.commercial.actors import Actor, NotFound

            organization_id = self._organization
            try:
                authorized = await CatalogProjection(
                    self._session,
                    Actor.product(organization_id, "PropertyInformation"),
                ).get_authorized_listing(
                    AuthorizedListingQuery(
                        purpose=EligibilityPurpose.AGENT_DISCLOSURE,
                        at=datetime.now(tz=UTC),
                        property_uuid=prop.id,
                    )
                )
            except (ListingNotEligible, NotFound):
                return {
                    "result": "unavailable",
                    "property_id": prop.property_key,
                    "name": prop.name,
                    "status": prop.status,
                    "customer_message": customer_availability_message(
                        prop.inactive_reason
                    ),
                }

        version = await self._accepted_version(prop)
        if version is None:
            return {"result": "temporarily_unavailable"}

        # Off the event loop: this runs on the same loop as the webhook and the
        # background worker, and the artifact is up to MAX_UPLOAD_BYTES of disk.
        markdown = await asyncio.to_thread(self._artifacts.read, version.artifact_path)
        if markdown is None:
            # The accepted artifact cannot be established. Return no document
            # rather than a stale one.
            return {"result": "temporarily_unavailable"}

        rendered = markdown.decode("utf-8")
        if authorized is not None:
            _, narrative = split_front_matter(rendered)
            rendered = _catalog_document(authorized, narrative)
        return {
            "result": "found",
            "property_id": prop.property_key,
            "name": prop.name,
            "status": prop.status,
            "inactive_reason": prop.inactive_reason,
            "document_version": version.version,
            "document_markdown": rendered,
        }

    async def _resolve(self, reference: str) -> Property | None:
        return await resolve_property(
            self._session, reference, self._organization
        )

    async def _accepted_version(self, prop: Property) -> PropertyDocumentVersion | None:
        return await accepted_version(self._session, prop)


def _physical_facts(metadata: dict[str, Any]) -> dict[str, Any]:
    """Facts copied from a document without its commercial Offer fields."""
    excluded = {
        "schema_version",
        "property_id",
        "name",
        "operation",
        "price_amount",
        "price_currency",
    }
    return {key: value for key, value in metadata.items() if key not in excluded}


def _catalog_document(listing: Any, narrative: str) -> str:
    """Compatibility Markdown projected from catalog truth, never legacy price."""
    offers = []
    for offer in listing.offers:
        price: str | None = (
            str(offer.price_amount) if offer.price_amount is not None else None
        )
        offers.append(
            {
                "operation": offer.operation,
                "price": price,
                "currency": offer.price_currency,
                "price_visibility": offer.price_visibility,
                "consultation_copy": offer.consultation_copy,
                "availability": offer.availability,
                "terms": offer.terms,
            }
        )
    facts = json.dumps(
        {
            "physical": listing.physical_facts,
            "publication": listing.listing_facts,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
    offer_json = json.dumps(
        offers, ensure_ascii=False, indent=2, sort_keys=True, default=str
    )
    return (
        f"# {listing.title}\n\n"
        f"Publicación autorizada: `{listing.listing_key}` · {listing.source_name}.\n\n"
        f"Atribución: {listing.attribution}\n\n"
        f"Disponibilidad: {listing.availability}\n\n"
        "## Ofertas autorizadas\n\n"
        f"```json\n{offer_json}\n```\n\n"
        "## Datos aprobados\n\n"
        f"```json\n{facts}\n```\n\n"
        "## Narrativa del documento de procedencia\n\n"
        f"{narrative.strip()}\n"
    )
