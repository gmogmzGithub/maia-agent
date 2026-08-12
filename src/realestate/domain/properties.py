"""Property ingestion and documented-fact retrieval (ADR-0010, P-045…P-053).

This module is the Deterministic Backend's authority over Property identity,
accepted document versions, and status. It is the only place that decides what
the Sales Role may be told about a Property.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AgentRole,
    Property,
    PropertyDocumentVersion,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.property_document import (
    PropertyDocument,
    ValidationError,
    normalize_name,
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


async def resolve_property(session: AsyncSession, reference: str) -> Property | None:
    """The Property a model-supplied *reference* names, or None.

    A readable key ('casa-roble') or the exact name ('Casa Roble'), compared by
    the P-048 normalisation. This is the one place that rule lives: the
    appointment and administrative surfaces resolve the same reference the same
    way, and neither needs the ingestion service to do it.
    """
    candidate = (reference or "").strip()
    if not candidate:
        return None

    by_key = (
        await session.execute(select(Property).where(Property.property_key == candidate))
    ).scalar_one_or_none()
    if by_key is not None:
        return by_key

    return (
        await session.execute(
            select(Property).where(Property.normalized_name == normalize_name(candidate))
        )
    ).scalar_one_or_none()


class PropertyService:
    def __init__(self, session: AsyncSession, artifacts: ArtifactStore) -> None:
        self._session = session
        self._artifacts = artifacts

    # -- Ingestion --------------------------------------------------------

    async def accept_upload(
        self, filename: str, content: bytes, actor_id: str
    ) -> AcceptedUpload:
        """Validate and atomically accept one Property Document.

        Raises ``ValidationError`` without persisting anything if the document
        is invalid or would collide. A valid first upload creates the Property
        as ``Active``; a valid replacement preserves the existing status (P-046).
        """
        document = validate_upload(filename, content)

        existing = await self._by_key(document.property_key)
        await self._reject_name_collision(document, existing)
        if existing is None:
            await self._reject_inventory_overflow()

        # Artifact first, then the transaction (P-050).
        checksum, artifact_path = self._artifacts.write(document.raw_bytes)

        try:
            if existing is None:
                accepted = await self._create_property(document, checksum, artifact_path)
            else:
                accepted = await self._add_version(
                    existing, document, checksum, artifact_path
                )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ValidationError(
                [
                    "The upload conflicted with an existing Property and was rejected. "
                    "No accepted document or status was changed."
                ]
            ) from exc

        await self._audit(
            actor_type="Developer",
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
        result = await self._session.execute(
            select(Property).where(Property.property_key == property_key)
        )
        return result.scalar_one_or_none()

    async def _reject_name_collision(
        self, document: PropertyDocument, existing: Property | None
    ) -> None:
        query = select(Property).where(Property.normalized_name == document.normalized_name)
        if existing is not None:
            query = query.where(Property.id != existing.id)
        collision = (await self._session.execute(query)).scalar_one_or_none()
        if collision is not None:
            raise ValidationError(
                [
                    f"name: {document.name!r} matches the existing Property "
                    f"{collision.name!r} ({collision.property_key}) after ignoring case, "
                    "whitespace, and accents. Names must stay unique."
                ]
            )

    async def _reject_inventory_overflow(self) -> None:
        count = (
            await self._session.execute(select(func.count()).select_from(Property))
        ).scalar_one()
        if count >= MAX_PROPERTIES:
            raise ValidationError(
                [
                    f"Stage 0 accepts at most {MAX_PROPERTIES} Properties and "
                    f"{count} already exist."
                ]
            )

    async def _create_property(
        self, document: PropertyDocument, checksum: str, artifact_path: Path
    ) -> AcceptedUpload:
        prop = Property(
            property_key=document.property_key,
            name=document.name,
            normalized_name=document.normalized_name,
            # A valid first upload creates the Property as Active (P-045).
            status=PropertyStatus.ACTIVE.value,
        )
        self._session.add(prop)
        await self._session.flush()  # INSERT ... RETURNING id

        version = self._new_version(prop, document, 1, checksum, artifact_path)
        self._session.add(version)
        await self._session.flush()
        prop.accepted_version_id = version.id

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
        actor_type: str,
        actor_id: str,
        action: str,
        subject_id: str,
        details: dict,
        subject_type: str = "Property",
    ) -> None:
        await record_audit(
            self._session,
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
    ) -> dict:
        """Resolve `get_property_information` under role-aware policy (P-053).

        ``reference`` is a readable Property Key or the Lead-facing name. A
        database UUID is never accepted; it would simply fail to resolve.

        The request is audited before the answer is returned, so "did the Agent
        actually consult the document?" is a question the product can answer
        from its own records rather than from a model transcript.
        """
        result = await self._property_information(reference, role)
        await self._audit(
            actor_type=role.value,
            actor_id=actor_id or "unknown-session",
            action="PropertyInformationRequested",
            subject_id=reference,
            details={"result": result["result"], "role": role.value},
        )
        return result

    async def _property_information(self, reference: str, role: AgentRole) -> dict:
        prop = await self._resolve(reference)
        if prop is None:
            return {"result": "not_found"}

        # An Inactive Property discloses no promotional content to the Sales
        # Role. The Administrative Role may inspect either status.
        if role is AgentRole.SALES and prop.status == PropertyStatus.INACTIVE.value:
            return {
                "result": "unavailable",
                "property_id": prop.property_key,
                "name": prop.name,
                "status": prop.status,
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

        return {
            "result": "found",
            "property_id": prop.property_key,
            "name": prop.name,
            "status": prop.status,
            "document_version": version.version,
            "document_markdown": markdown.decode("utf-8"),
        }

    async def _resolve(self, reference: str) -> Property | None:
        return await resolve_property(self._session, reference)

    async def _accepted_version(self, prop: Property) -> PropertyDocumentVersion | None:
        if prop.accepted_version_id is None:
            return None
        return await self._session.get(PropertyDocumentVersion, prop.accepted_version_id)
