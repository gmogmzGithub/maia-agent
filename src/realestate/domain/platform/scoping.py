"""The scoping table: for every table, whose data is in it.

This module is the answer to a question that used to have no single place to
live. "Is ``inbox_messages`` organization data?" was answered by reading a query
and hoping. With a second Brokerage Organization that is not good enough, so the
answer is written down once, here, and three separate mechanisms read it:

* a test asserts that **every** table in the metadata appears below, so a new
  table cannot be added without somebody deciding what it holds;
* the per-Organization export walks it, so a table nobody thought about is a
  failing count rather than a silent omission;
* deletion walks it in reverse dependency order, so removing an Organization's
  data does not fail halfway through on a foreign key.

Three classifications, and the difference between them matters:

``ORGANIZATION_ROOT``
    The ``organizations`` table itself. Scoped by ``id`` rather than by
    ``organization_id``, which is why it needs its own kind instead of a special
    case inside the loop.

``ORGANIZATION``
    Rows belong to exactly one Organization, named by an ``organization_id``
    column. Since Stage 9 that column is present on every such table even where a
    join could have reached it — a query that forgets the join answers with
    somebody else's work, while a column and a composite foreign key make the row
    and its parent unable to disagree in the first place. The column is also what
    lets the export and the deletion below address a table without knowing
    anything about its shape.

``PLATFORM``
    Deliberately not one Organization's data. Every entry carries a written
    reason, and the reason has to survive being read by somebody looking for a
    leak. "It was easier" is not one of them.

Two further pieces of policy live here because they are properties of a table
rather than of a caller:

``withheld``
    Columns an export must never carry. Salts, token digests, credential
    fingerprints and runtime session handles. An export is something a customer
    receives; a salt in it would make the pseudonymisation reversible and a token
    digest would hand over a live capability.

``content``
    Whether a row is *conversation content* rather than commercial record.
    ADR-0026 already separates the two lifetimes; deletion needs the same
    separation, because "delete our conversations" and "delete our company" are
    different requests and only one of them collides with a retention hold.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from realestate.db.engine import Base

# Imported for its side effect: the metadata this module reflects over is only
# populated once the model classes have been defined. Reading an empty metadata
# would make ``unclassified_tables`` report nothing missing, which is the one
# answer this module must never give by accident.
import realestate.db.models  # noqa: F401  (registers every table on Base)


class ScopeKind(str, enum.Enum):
    ORGANIZATION_ROOT = "OrganizationRoot"
    ORGANIZATION = "Organization"
    PLATFORM = "Platform"


@dataclass(frozen=True)
class TableScope:
    """One table's classification, and what follows from it."""

    table: str
    kind: ScopeKind
    #: Required for ``PLATFORM``: why this is not one Organization's data.
    reason: str = ""
    #: Conversation content rather than commercial record (ADR-0026).
    content: bool = False
    #: Columns an export must not carry, and why they are dangerous.
    withheld: tuple[str, ...] = field(default_factory=tuple)

    @property
    def scope_column(self) -> str | None:
        if self.kind is ScopeKind.ORGANIZATION_ROOT:
            return "id"
        if self.kind is ScopeKind.ORGANIZATION:
            return "organization_id"
        return None


def _org(
    table: str,
    *,
    content: bool = False,
    withheld: tuple[str, ...] = (),
) -> TableScope:
    return TableScope(
        table=table, kind=ScopeKind.ORGANIZATION, content=content, withheld=withheld
    )


def _platform(table: str, reason: str) -> TableScope:
    return TableScope(table=table, kind=ScopeKind.PLATFORM, reason=reason)


# --------------------------------------------------------------------------
# The table. Ordered by the stage that introduced each group, because that is
# the order somebody auditing this reads the rest of the repository in.
# --------------------------------------------------------------------------

SCOPES: tuple[TableScope, ...] = (
    TableScope(table="organizations", kind=ScopeKind.ORGANIZATION_ROOT),
    # ---- Stage 0/1: properties, conversations, delivery ------------------
    _org("properties"),
    _org("property_document_versions"),
    _org("leads"),
    _org("lead_engagement_cycles"),
    _org("conversations"),
    _org("lead_followups"),
    _org("inbox_messages", content=True),
    _org("inbox_groups", content=True),
    _org("outbox_messages", content=True),
    _org("delivery_statuses", content=True),
    _org("consent_records"),
    _org("suppression_records"),
    _org("outbound_decisions"),
    _org("admin_messages", content=True),
    _org("channel_cursors"),
    _org("availability_snapshots", content=True),
    _org("appointments"),
    _org(
        "agent_sessions",
        content=True,
        # A live handle into the Hermes runtime. Exporting it would hand over a
        # conversation somebody could still steer.
        withheld=("hermes_session_id", "gateway_session_id"),
    ),
    # ``audit_events`` is Organization data with one documented exception: a row
    # about the platform itself — provisioning, a support grant — has no
    # Organization, which the table's own check constraint restricts to
    # ``actor_type = 'Platform'``. The export therefore reads it exactly like
    # every other Organization table and the platform rows simply do not match.
    _org("audit_events"),
    # ---- Stage 2/3: the commercial system of record -----------------------
    _org("organization_members"),
    _org("contacts"),
    _org("contact_channel_identities"),
    _org("property_needs"),
    _org("property_need_criteria"),
    _org("opportunities"),
    _org("commercial_transactions"),
    _org("opportunity_origins"),
    _org("opportunity_stage_transitions"),
    _org("opportunity_assignments"),
    _org("assignment_queue_entries"),
    _org("next_actions"),
    _org("opportunity_exceptions"),
    _org("commercial_command_receipts"),
    _org("advisor_absences"),
    _org("property_experts"),
    _org("conversation_handling"),
    _org("human_handoff_requests"),
    _org("internal_alerts"),
    _org("appointment_reminders"),
    # ---- Stage 4: the authoritative catalog -------------------------------
    _org("developments"),
    _org("unit_models"),
    _org("catalog_listings"),
    _org("listing_offers"),
    _org("listing_media"),
    # ---- Stage 5: the public site ----------------------------------------
    _org(
        "saved_collections",
        content=True,
        # The cookie value's digest. Whoever holds the plaintext holds the
        # collection; the digest is what an attacker would want to confirm one.
        withheld=("access_token_hash",),
    ),
    _org("saved_collection_items", content=True),
    _org("shared_selections", content=True, withheld=("access_token_hash",)),
    _org("website_conversations", content=True),
    _org("website_messages", content=True),
    _org("channel_handoffs", content=True, withheld=("token_hash",)),
    _org("public_analytics_events"),
    # ---- Stage 6: external inventory -------------------------------------
    _org("external_listing_candidates"),
    _org("external_offer_candidates"),
    _org("inventory_source_health"),
    _org("listing_revalidations"),
    # ---- Stage 7: reactivation and campaigns -----------------------------
    _org("approved_message_templates"),
    _org("reactivation_candidates"),
    _org("development_campaigns"),
    _org("campaign_audience_members"),
    _org("marketing_touches"),
    # ---- Stage 8: measurement and paid visibility ------------------------
    _org(
        "pseudonym_salts",
        # The single most dangerous column in the schema. With the salt, every
        # pseudonymous reference in the analytics store becomes reversible by
        # anybody who can guess the input — which for a phone number is nobody's
        # idea of hard.
        withheld=("salt",),
    ),
    _org("analytics_outbox"),
    _org("domain_events"),
    _org("funnel_aggregates"),
    _org("sponsorship_price_catalogs"),
    _org("sponsorship_price_items"),
    _org("sponsorship_surface_capacity"),
    _org("sponsorship_campaigns"),
    _org("sponsorship_quotes"),
    _org("sponsorship_capacity_reservations"),
    _org("sponsored_eligibility_records"),
    _org("sponsorship_delivery_days"),
    _org("sponsorship_contact_attributions"),
    _org("sponsored_exposure_counters"),
    _org("sponsorship_report_links", withheld=("token_digest",)),
    _org("harm_signals"),
    # ---- Stage 9: the platform's own records -----------------------------
    _org("organization_configuration_versions"),
    _org(
        "organization_secret_references",
        # A digest of a credential is a confirmation oracle for anybody who can
        # guess it. The reference — the *name* — is exported, because a customer
        # is entitled to know where their credential is expected to come from.
        withheld=("fingerprint",),
    ),
    _org("organization_channel_bindings"),
    _org("organization_entitlements"),
    _org("support_access_grants"),
    _org("organization_usage_periods"),
    _org("organization_import_runs"),
    _org("organization_import_findings"),
    _org("organization_retention_holds"),
    _org("organization_data_exports"),
    _org("organization_data_deletions"),
    # ---- Deliberately platform-wide --------------------------------------
    _platform(
        "measurement_definitions",
        "One frozen rulebook of counting thresholds, shared by every "
        "Organization so a report reproduced later resolves the same rules. It "
        "contains no Organization's data and no Organization may change it; "
        "per-Organization thresholds would make two customers' numbers "
        "incomparable while looking identical (ADR-0044).",
    ),
    _org("projection_runs"),
    _platform(
        "organization_provisioning_runs",
        "A provisioning run may exist before its Organization does — that is "
        "exactly what makes a partially created Organization resumable — so its "
        "``organization_id`` is nullable and it cannot be the scope. The run is "
        "platform history about an Organization, not the Organization's own "
        "record.",
    ),
    _platform(
        "organization_provisioning_steps",
        "The steps of a provisioning run, and unscoped for the same reason it "
        "is: the step that creates the Organization row runs before there is an "
        "Organization to attribute it to.",
    ),
)


#: Columns that point *back* at a table which points at them. There is exactly
#: one — ``properties.accepted_version_id`` names the document version a Property
#: currently accepts, while every version names its Property — and it is declared
#: here because the dependency sort cannot break a cycle. Deletion clears these
#: pointers before it removes anything, or it fails halfway on a foreign key with
#: a customer waiting.
CIRCULAR_POINTERS: tuple[tuple[str, str], ...] = (
    ("properties", "accepted_version_id"),
)


SCOPE_BY_TABLE: dict[str, TableScope] = {scope.table: scope for scope in SCOPES}


def scope_for(table: str) -> TableScope:
    """The classification of one table, or a loud failure.

    Raising rather than returning a default is the point. A table with no
    decision recorded about it is the exact condition this module exists to make
    impossible, and a permissive default would hide it.
    """
    try:
        return SCOPE_BY_TABLE[table]
    except KeyError:
        raise KeyError(
            f"{table!r} has no entry in the scoping table. Add one to "
            "realestate.domain.platform.scoping.SCOPES: decide whether it holds "
            "one Organization's data or is deliberately platform-wide, and say "
            "why."
        ) from None


def organization_scopes() -> tuple[TableScope, ...]:
    """Every table an Organization's data lives in, root first.

    Ordered by the metadata's own dependency sort, so inserting in this order
    and deleting in the reverse of it both satisfy the foreign keys. Derived
    rather than hand-maintained: a hand-written order is wrong the first time
    somebody adds a table and nothing notices until a deletion fails halfway.
    """
    order = {table.name: index for index, table in enumerate(Base.metadata.sorted_tables)}
    scoped = [
        scope
        for scope in SCOPES
        if scope.kind in (ScopeKind.ORGANIZATION_ROOT, ScopeKind.ORGANIZATION)
    ]
    return tuple(sorted(scoped, key=lambda scope: order.get(scope.table, 10_000)))


def qualified_name(table: str) -> str:
    """``schema.table`` when the table lives in one, otherwise the bare name.

    The analytics tables live in their own PostgreSQL schema, which every raw
    statement the lifecycle module issues has to say out loud.
    """
    for mapped in Base.metadata.tables.values():
        if mapped.name == table:
            return f"{mapped.schema}.{table}" if mapped.schema else table
    raise KeyError(f"{table!r} is not a mapped table")


def unclassified_tables() -> tuple[str, ...]:
    """Tables the metadata knows about and the scoping table does not.

    Read by a test rather than at runtime. It is the guard that keeps this
    module honest as the schema grows.
    """
    known = set(SCOPE_BY_TABLE)
    return tuple(
        sorted(
            table.name
            for table in Base.metadata.tables.values()
            if table.name not in known
        )
    )


def mismatched_scope_columns() -> tuple[str, ...]:
    """Tables classified as Organization data without the column to prove it."""
    problems: list[str] = []
    by_name = {table.name: table for table in Base.metadata.tables.values()}
    for scope in SCOPES:
        column = scope.scope_column
        if column is None:
            continue
        mapped = by_name.get(scope.table)
        if mapped is None:
            problems.append(f"{scope.table} (not a mapped table)")
        elif column not in mapped.columns:
            problems.append(f"{scope.table} (no {column} column)")
    return tuple(problems)
