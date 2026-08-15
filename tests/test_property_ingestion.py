"""Property ingestion and role-aware retrieval against real PostgreSQL.

These exercise the Deterministic Backend's authority directly, with no model in
the loop — the property ADR-0004 exists to make possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AuditEvent,
    Property,
    PropertyDocumentVersion,
    PropertyStatus,
)
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.domain.property_document import ValidationError, validate_upload
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()
V2 = (FIXTURES / "casa-roble-v2.md").read_bytes()

pytestmark = requires_postgres


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        # Each test starts from an empty inventory. Rows that reference a
        # Property go first: another suite's leftovers would otherwise make
        # this fixture fail on a foreign key rather than clean up.
        await reset_property_inventory(session)
        await session.execute(delete(AuditEvent))
        await session.commit()
    yield db
    await db.dispose()


@pytest.fixture
def artifacts(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture
async def service(database, artifacts):
    async with database.session_scope() as session:
        yield PropertyService(session, artifacts)


def renamed(source: bytes, name: str) -> bytes:
    text = source.decode("utf-8")
    current = validate_upload("property.md", source).name
    return (
        text.replace(f"name: {current}", f"name: {name}", 1)
        .replace(f"# {current}", f"# {name}", 1)
        .encode("utf-8")
    )


def rekeyed(source: bytes, key: str) -> bytes:
    return source.decode("utf-8").replace("property_id: casa-roble", f"property_id: {key}", 1).encode()


# --- First upload -----------------------------------------------------------


async def test_a_first_valid_upload_creates_an_active_property(service) -> None:
    accepted = await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    assert accepted.created
    assert accepted.version == 1
    assert accepted.status == PropertyStatus.ACTIVE.value


async def test_the_accepted_bytes_are_stored_unchanged(service, artifacts) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    result = await service.get_property_information("casa-roble", AgentRole.SALES)

    # The uploaded Markdown is never rewritten to carry the generated UUID.
    assert result["document_markdown"].encode("utf-8") == V1
    assert "property_id: casa-roble" in result["document_markdown"]


async def test_the_uuid_is_never_written_into_the_document(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        markdown = (
            await PropertyService(session, service._artifacts).get_property_information(
                "casa-roble", AgentRole.SALES
            )
        )["document_markdown"]

    assert str(prop.id) not in markdown


async def test_the_upload_is_audited(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    async with database.session_scope() as session:
        events = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "PropertyDocumentAccepted")
            )
        ).scalars().all()

    assert len(events) == 1
    assert events[0].actor_id == "developer"
    assert events[0].subject_id == "casa-roble"
    assert events[0].details["version"] == 1


# --- Replacement ------------------------------------------------------------


async def test_a_valid_replacement_adds_a_version_and_becomes_current(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    accepted = await service.accept_upload("casa-roble.md", V2, actor_id="developer")

    assert not accepted.created
    assert accepted.version == 2

    result = await service.get_property_information("casa-roble", AgentRole.SALES)
    assert result["document_version"] == 2
    assert "price_amount: 3200000" in result["document_markdown"]


async def test_earlier_versions_remain_immutable(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    await service.accept_upload("casa-roble.md", V2, actor_id="developer")

    async with database.session_scope() as session:
        versions = (
            await session.execute(
                select(PropertyDocumentVersion).order_by(PropertyDocumentVersion.version)
            )
        ).scalars().all()

    assert [v.version for v in versions] == [1, 2]
    assert versions[0].checksum != versions[1].checksum
    assert Path(versions[0].artifact_path).read_bytes() == V1


async def test_a_replacement_preserves_an_inactive_status(service, database) -> None:
    # P-046: updating an Inactive Property must not reactivate it.
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()

    accepted = await service.accept_upload("casa-roble.md", V2, actor_id="developer")

    assert accepted.status == PropertyStatus.INACTIVE.value


async def test_an_invalid_replacement_changes_nothing(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    malformed = V2.replace(b"price_amount: 3200000", b"price_amount: not-a-number")

    with pytest.raises(ValidationError):
        await service.accept_upload("casa-roble.md", malformed, actor_id="developer")

    result = await service.get_property_information("casa-roble", AgentRole.SALES)
    assert result["document_version"] == 1
    assert "price_amount: 3000000" in result["document_markdown"]


# --- Identity ---------------------------------------------------------------


async def test_a_different_property_key_creates_a_different_property(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    other = renamed(rekeyed(V1, "casa-encino"), "Casa Encino")
    accepted = await service.accept_upload("casa-encino.md", other, actor_id="developer")

    assert accepted.created
    assert accepted.property_key == "casa-encino"


async def test_a_colliding_name_is_rejected_atomically(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    colliding = renamed(rekeyed(V1, "casa-encino"), "cása  roble")

    with pytest.raises(ValidationError) as caught:
        await service.accept_upload("casa-encino.md", colliding, actor_id="developer")

    assert "unique" in str(caught.value)
    assert (await service.get_property_information("casa-encino", AgentRole.SALES))[
        "result"
    ] == "not_found"


async def test_a_property_may_rename_itself(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    accepted = await service.accept_upload(
        "casa-roble.md", renamed(V2, "Casa Roble Norte"), actor_id="developer"
    )

    assert accepted.name == "Casa Roble Norte"
    assert (await service.get_property_information("Casa Roble Norte", AgentRole.SALES))[
        "result"
    ] == "found"


# --- Retrieval policy (P-053) -----------------------------------------------


@pytest.mark.parametrize("reference", ["casa-roble", "Casa Roble", "casa  roble", "CÁSA ROBLE"])
async def test_a_property_resolves_by_key_or_normalised_name(service, reference) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    assert (await service.get_property_information(reference, AgentRole.SALES))[
        "result"
    ] == "found"


async def test_an_unknown_reference_is_not_found_when_inventory_is_empty(service) -> None:
    assert (await service.get_property_information("casa-fantasma", AgentRole.SALES))[
        "result"
    ] == "not_found"


async def test_a_database_uuid_is_not_an_accepted_reference(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    async with database.session_scope() as session:
        uuid_value = str((await session.execute(select(Property.id))).scalar_one())

    assert (await service.get_property_information(uuid_value, AgentRole.SALES))[
        "result"
    ] == "not_found"


async def test_the_sales_role_gets_no_document_for_an_inactive_property(
    service, database
) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()

    result = await service.get_property_information("casa-roble", AgentRole.SALES)

    assert result["result"] == "unavailable"
    assert result["status"] == "Inactive"
    assert "document_markdown" not in result
    # No promotional content leaks through any field.
    assert "Alberca" not in str(result)


async def test_the_administrative_role_may_inspect_an_inactive_property(
    service, database
) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()

    result = await service.get_property_information("casa-roble", AgentRole.ADMINISTRATIVE)

    assert result["result"] == "found"
    assert result["status"] == "Inactive"
    assert "Alberca" in result["document_markdown"]


async def test_a_missing_artifact_returns_no_stale_document(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    async with database.session_scope() as session:
        version = (await session.execute(select(PropertyDocumentVersion))).scalar_one()
        Path(version.artifact_path).unlink()

    result = await service.get_property_information("casa-roble", AgentRole.SALES)

    assert result["result"] == "temporarily_unavailable"
    assert "document_markdown" not in result


async def test_every_retrieval_is_audited(service, database) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    await service.get_property_information("casa-roble", AgentRole.SALES, actor_id="sess-1")

    async with database.session_scope() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "PropertyInformationRequested"
                )
            )
        ).scalars().one()

    assert event.actor_id == "sess-1"
    assert event.actor_type == "Sales"
    assert event.details["result"] == "found"


# --- Resolving a reference ----------------------------------------------------


@pytest.mark.parametrize("reference", ["", "   ", None])
async def test_a_blank_reference_resolves_to_nothing(service, reference) -> None:
    """Not an error and not a wildcard: the Agent must ask which Property."""
    from realestate.domain.properties import resolve_property

    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    assert await resolve_property(service._session, reference) is None


async def test_an_unknown_reference_is_not_found_when_inventory_is_not_empty(service) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    assert (
        await service.get_property_information("casa-fantasma", AgentRole.SALES)
    )["result"] == "not_found"


# --- The inventory ceiling ----------------------------------------------------


async def test_the_stage_0_inventory_ceiling_is_enforced(service) -> None:
    """Ten is the accepted Stage 0 bound; an eleventh is rejected outright."""
    from realestate.domain.properties import MAX_PROPERTIES

    for index in range(MAX_PROPERTIES):
        key = f"casa-{index:02d}"
        await service.accept_upload(
            f"{key}.md",
            renamed(rekeyed(V1, key), f"Casa {index:02d}"),
            actor_id="developer",
        )

    with pytest.raises(ValidationError) as caught:
        await service.accept_upload(
            "casa-extra.md",
            renamed(rekeyed(V1, "casa-extra"), "Casa Extra"),
            actor_id="developer",
        )

    assert f"at most {MAX_PROPERTIES} Properties" in caught.value.errors[0]


async def test_replacing_a_document_at_the_ceiling_is_still_allowed(service) -> None:
    """The bound is on Properties, not uploads: a Broker must still be able to
    correct the tenth document."""
    from realestate.domain.properties import MAX_PROPERTIES

    for index in range(MAX_PROPERTIES):
        key = f"casa-{index:02d}"
        await service.accept_upload(
            f"{key}.md",
            renamed(rekeyed(V1, key), f"Casa {index:02d}"),
            actor_id="developer",
        )

    accepted = await service.accept_upload(
        "casa-00.md", renamed(rekeyed(V2, "casa-00"), "Casa 00"), actor_id="developer"
    )

    assert not accepted.created
    assert accepted.version == 2


# --- A Property whose accepted document cannot be established ------------------


async def test_a_property_with_no_accepted_version_is_temporarily_unavailable(
    service, database
) -> None:
    """No document is a better answer than a stale one."""
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    async with database.session_scope() as session:
        prop = (
            await session.execute(
                select(Property).where(Property.property_key == "casa-roble")
            )
        ).scalar_one()
        prop.accepted_version_id = None
        await session.commit()

    async with database.session_scope() as session:
        result = await PropertyService(
            session, service._artifacts
        ).get_property_information("casa-roble", AgentRole.SALES)

    assert result == {"result": "temporarily_unavailable"}


async def test_a_missing_artifact_returns_no_document_rather_than_a_stale_one(
    service, artifacts
) -> None:
    await service.accept_upload("casa-roble.md", V1, actor_id="developer")
    for path in (artifacts._root).rglob("*.md"):
        path.unlink()

    result = await service.get_property_information("casa-roble", AgentRole.SALES)

    assert result == {"result": "temporarily_unavailable"}


# --- A collision the pre-checks did not catch ----------------------------------


async def test_a_collision_at_commit_time_changes_nothing(
    service, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-checks are advisory; the unique constraints are the guarantee.

    A rejection here must leave the current accepted document and status
    untouched rather than half-applying the upload.
    """
    from sqlalchemy.exc import IntegrityError

    await service.accept_upload("casa-roble.md", V1, actor_id="developer")

    async def collide() -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(service._session, "commit", collide)

    with pytest.raises(ValidationError) as caught:
        await service.accept_upload("casa-roble.md", V2, actor_id="developer")

    assert "No accepted document or status was changed." in caught.value.errors[0]
