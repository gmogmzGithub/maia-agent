"""Product tables (ADR-0006).

Only what the current checkpoint needs. Checkpoint 1 adds Property identity and
status, immutable document versions with an accepted-version pointer, the audit
trail, and the trusted Hermes session binding.

Two identifiers per Property (P-050): PostgreSQL generates the opaque UUID ``id``
that owns internal relationships, while the readable immutable ``property_key``
slug from the Markdown is the business key used by uploads and product tools.
The UUID is never written back into the document and is never accepted from the
Model.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
# Aliased: ``InboxMessage.text`` shadows the bare name inside that class body.
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from realestate.db.engine import Base


class PropertyStatus(str, enum.Enum):
    """The two Stage 0 statuses (P-010, S-010). Never sourced from front matter."""

    ACTIVE = "Active"
    INACTIVE = "Inactive"


class PropertyInactiveReason(str, enum.Enum):
    """Why an Inactive Property cannot be offered to a new Lead."""

    SOLD = "Sold"
    RENTED = "Rented"
    RESERVED = "Reserved"
    TEMPORARILY_UNAVAILABLE = "TemporarilyUnavailable"
    WITHDRAWN = "Withdrawn"
    UNSPECIFIED = "Unspecified"


class AgentRole(str, enum.Enum):
    """Separate conversational roles with separate authority (ADR-0001)."""

    SALES = "Sales"
    ADMINISTRATIVE = "Administrative"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # The readable immutable Property Key from the Markdown (P-048).
    property_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Case-, whitespace- and diacritic-insensitive form; unique across Stage 0.
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PropertyStatus.ACTIVE.value
    )
    inactive_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Private operational data. It is never stored in the Property Document or
    # returned by the ordinary property-information tool.
    visit_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_document_versions.id", use_alter=True, name="fk_accepted_version"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    accepted_version: Mapped["PropertyDocumentVersion | None"] = relationship(
        foreign_keys=[accepted_version_id], post_update=True, lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Active', 'Inactive')", name="ck_properties_status"
        ),
        CheckConstraint(
            "(status = 'Active' AND inactive_reason IS NULL) OR "
            "(status = 'Inactive' AND inactive_reason IN "
            "('Sold', 'Rented', 'Reserved', 'TemporarilyUnavailable', "
            "'Withdrawn', 'Unspecified'))",
            name="ck_properties_inactive_reason",
        ),
    )


class PropertyDocumentVersion(Base):
    """One immutable accepted document version.

    Rows are append-only. A replacement adds a version and moves the Property's
    accepted-version pointer; it never rewrites an existing row (P-046).
    """

    __tablename__ = "property_document_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # sha256 of the exact accepted bytes; also the artifact's content address.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # The parsed front matter, kept for audit and for compact administrative
    # views. The artifact remains the authoritative content.
    document_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("property_uuid", "version", name="uq_property_version"),
        Index("ix_property_document_versions_property", "property_uuid"),
    )


class AuditEvent(Base):
    """Append-only history linking actor, action, subject, and result."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_audit_events_subject", "subject_type", "subject_id"),)


class Lead(Base):
    """A person who contacts the Broker through WhatsApp.

    Stable across time. Engagement cycles come and go beneath it (ADR-0012);
    identity, audit history, and the Follow-up Opt-out persist here.
    """

    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # The Lead's WhatsApp id as Meta reports it (digits, no '+').
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    profile_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    follow_up_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# One fixed 30-day period of automated engagement (P-004).
ENGAGEMENT_CYCLE_DAYS = 30


class LeadEngagementCycle(Base):
    """One immutable 30-day engagement period.

    ``expires_at`` is set once, at creation. Messages inside the cycle continue
    it without moving the deadline; a message after expiry opens a *new* cycle
    linked to the same Lead and never reopens this one (ADR-0012).
    """

    __tablename__ = "lead_engagement_cycles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # The follow-up sweep asks for live cycles on every poll interval.
    __table_args__ = (
        Index("ix_lead_engagement_cycles_active", "expires_at", "started_at"),
    )

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at


class Conversation(Base):
    """One WhatsApp thread, scoped to one engagement cycle.

    The FIFO lane is per Conversation: at most one Inbox group may be active in
    it at a time, while separate Conversations proceed independently (P-028).
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_engagement_cycles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Our own WhatsApp number that received the message.
    phone_number_id: Mapped[str] = mapped_column(String(40), nullable=False)
    # The Property this Conversation is about, once identified. Never guessed
    # from the set of Active Properties (P-049).
    property_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # PostgreSQL does not index a foreign key on its own, and the gate's
    # service-window lookup joins through this column on every request.
    __table_args__ = (Index("ix_conversations_lead", "lead_id"),)


class LeadFollowUpStatus(str, enum.Enum):
    """Product-originated lead follow-up lifecycle."""

    ENQUEUED = "Enqueued"
    SKIPPED = "Skipped"
    # The Outbound Eligibility Gate refused the send (ADR-0045). The attempt is
    # recorded rather than dropped, so a follow-up that never went out is
    # visible to the operation together with the decision that stopped it.
    BLOCKED = "Blocked"


class LeadFollowUp(Base):
    """One follow-up attempt for one Lead cycle day under one named policy.

    The cadence is a *versioned pilot hypothesis*, not database truth, so the
    valid days live in ``domain/followups.py`` rather than in a CHECK
    constraint: changing the hypothesis must not require a schema migration,
    and rows written under an earlier version must stay readable. The row is
    also the idempotency record that prevents a worker restart from creating a
    second follow-up for the same cycle/day.
    """

    __tablename__ = "lead_followups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_engagement_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="WhatsApp")
    # Which named cadence hypothesis produced this attempt. Retained so a report
    # written after the policy changes can still explain why the day was chosen.
    policy_id: Mapped[str] = mapped_column(String(60), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=LeadFollowUpStatus.ENQUEUED.value
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_messages.id", ondelete="SET NULL"), nullable=True
    )
    # The eligibility decision that allowed or refused this attempt (ADR-0045).
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("channel = 'WhatsApp'", name="ck_lead_followups_channel"),
        CheckConstraint(
            "status IN ('Enqueued', 'Skipped', 'Blocked')",
            name="ck_lead_followups_status",
        ),
        UniqueConstraint(
            "cycle_id", "day_number", "channel", name="uq_lead_followup_cycle_day"
        ),
        Index("ix_lead_followups_due", "status", "due_at"),
    )


class InboxStatus(str, enum.Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    PROCESSED = "Processed"
    FAILED = "Failed"


class InboxMessage(Base):
    """One durably accepted inbound WhatsApp message.

    Every message stays an individual record even when several are combined
    into one Hermes turn, and no failed message is ever deleted (ADR-0005).
    The complete authenticated Meta object is retained so the Click-to-WhatsApp
    referral payload can be inspected before any mapping is designed (P-049,
    V-001).
    """

    __tablename__ = "inbox_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Meta's message identifier — the idempotency key for duplicate webhooks.
    wamid: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    from_wa_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    raw_message: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InboxStatus.PENDING.value
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inbox_groups.id", use_alter=True, name="fk_inbox_message_group"),
        nullable=True,
    )
    # Attempts belong to the message, not the group: regrouping after a failure
    # must not reset the P-035 ceiling of three.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Processing', 'Processed', 'Failed')",
            name="ck_inbox_messages_status",
        ),
        # The claim query: pending messages of one Conversation in arrival order.
        Index("ix_inbox_messages_lane", "conversation_id", "status", "sent_at"),
        # The eligibility gate's most-recent-inbound lookups (ADR-0045).
        Index(
            "ix_inbox_messages_recent",
            "conversation_id",
            sql_text("persisted_at DESC"),
        ),
    )


class InboxGroupStatus(str, enum.Enum):
    PROCESSING = "Processing"
    SETTLED = "Settled"
    FAILED = "Failed"


class InboxGroup(Base):
    """The claimable unit of Inbox work: the pending messages of one Conversation.

    Claiming is fenced by ``claim_token`` and bounded by a two-minute lease
    renewed every 30 seconds. An expired lease returns the work to Pending and
    consumes one of three attempts, and the expired owner cannot settle it
    afterwards (P-038).
    """

    __tablename__ = "inbox_groups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InboxGroupStatus.PROCESSING.value
    )
    claim_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Start of the in-flight reconciliation window (P-034).
    turn_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Processing', 'Settled', 'Failed')", name="ck_inbox_groups_status"
        ),
        # At most one active Inbox group per Conversation (P-028, P-037). The
        # database enforces the lane rather than trusting worker coordination.
        Index(
            "uq_active_group_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text("status = 'Processing'"),
        ),
    )


class OutboxStatus(str, enum.Enum):
    PENDING = "Pending"
    SENDING = "Sending"
    SENT = "Sent"
    FAILED = "Failed"
    # The request may have reached Meta but no conclusive result came back.
    # Never replayed automatically (P-036).
    DELIVERY_UNKNOWN = "DeliveryUnknown"


class OutboxMessage(Base):
    """One outbound intent, persisted before any delivery is attempted.

    Hermes output is not automatically a WhatsApp reply: a draft becomes an
    Outbox row only after response settlement, annotated with every Inbox
    identifier it covers (P-034).
    """

    __tablename__ = "outbox_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    inbox_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbox_groups.id"), nullable=True
    )
    # Idempotency: at most one Outbox row per (group, kind).
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    to_wa_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    covered_inbox_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutboxStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Sending', 'Sent', 'Failed', 'DeliveryUnknown')",
            name="ck_outbox_messages_status",
        ),
        Index("ix_outbox_due", "status", "next_attempt_at"),
        # The eligibility gate's "did we write last?" lookup (ADR-0045).
        Index(
            "ix_outbox_conversation_recent",
            "conversation_id",
            sql_text("created_at DESC"),
        ),
    )


class DeliveryStatus(Base):
    """A Meta delivery-status callback, reconciled onto its Outbox row.

    Persisted as product state rather than written to a debug log (TC-006).
    """

    __tablename__ = "delivery_statuses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_messages.id", ondelete="CASCADE"), nullable=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_message_id", "status", name="uq_delivery_status_event"
        ),
    )


class OutboundInitiation(str, enum.Enum):
    """Who started an outbound message (ADR-0045).

    The distinction is not cosmetic. A Reactive message answers concrete
    messages the Contact just sent; a BusinessInitiated one is the operation
    reaching out. Only the second needs consent, a template, and a purpose that
    the Contact has not refused.
    """

    REACTIVE = "Reactive"
    BUSINESS_INITIATED = "BusinessInitiated"


class OutboundOutcome(str, enum.Enum):
    QUEUED = "Queued"
    DENIED = "Denied"


class ConsentCategory(str, enum.Enum):
    """WhatsApp message categories, kept separate because consent is per use."""

    MARKETING = "Marketing"
    UTILITY = "Utility"
    SERVICE = "Service"


class ConsentState(str, enum.Enum):
    GRANTED = "Granted"
    REVOKED = "Revoked"


class ConsentRecord(Base):
    """One dated statement about permission to contact one Lead.

    Append-only: a later record supersedes an earlier one for the same
    (lead, channel, category) rather than editing it, so the evidence of what
    was permitted *at the time* survives. Product has no production path that
    writes ``Granted`` yet — capturing marketing consent needs a real form,
    privacy notice, and legal review — so the gate refuses every send that
    depends on it (ADR-0045).
    """

    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="WhatsApp")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False)
    # How Product learned this: which product path recorded it.
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    # The Contact's own words when the record came from something they wrote.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("channel = 'WhatsApp'", name="ck_consent_records_channel"),
        CheckConstraint(
            "category IN ('Marketing', 'Utility', 'Service')",
            name="ck_consent_records_category",
        ),
        CheckConstraint(
            "state IN ('Granted', 'Revoked')", name="ck_consent_records_state"
        ),
        Index(
            "ix_consent_records_current",
            "lead_id",
            "channel",
            "category",
            "recorded_at",
        ),
    )


class SuppressionRecord(Base):
    """Durable evidence that a Lead must not receive business-initiated contact.

    Deliberately outlives conversation content: the reason not to write to
    somebody has to survive the expiry of the messages that produced it.
    Revoking requires a new decision, so the row is closed with ``revoked_at``
    rather than deleted.
    """

    __tablename__ = "suppression_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="WhatsApp")
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="BusinessInitiated"
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_inbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbox_messages.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("channel = 'WhatsApp'", name="ck_suppression_records_channel"),
        CheckConstraint(
            "scope IN ('BusinessInitiated', 'All')", name="ck_suppression_records_scope"
        ),
        # At most one *active* suppression per Lead and channel, which makes
        # recording an opt-out idempotent under concurrent webhook deliveries.
        Index(
            "uq_suppression_active",
            "lead_id",
            "channel",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
    )


class OutboundDecision(Base):
    """One append-only record of the Outbound Eligibility Gate's answer.

    Every outbound message, reactive or not, produces exactly one of these
    before it can exist as an Outbox row. Denials are kept too: "we did not
    write to this person, and here is why" is the operationally interesting
    fact, and it is the only evidence that the gate ran (ADR-0045).
    """

    __tablename__ = "outbound_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    initiation: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    # A stable machine-readable denial code; NULL when the outcome is Queued.
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which inbound messages the caller says this answers. Empty for a
    # business-initiated message, which is exactly what makes it one.
    trigger_inbox_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    template_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    template_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # When the Meta customer-service window closes, as Product computed it.
    service_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbox_messages.id", ondelete="SET NULL"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "initiation IN ('Reactive', 'BusinessInitiated')",
            name="ck_outbound_decisions_initiation",
        ),
        CheckConstraint(
            "outcome IN ('Queued', 'Denied')", name="ck_outbound_decisions_outcome"
        ),
        CheckConstraint(
            "(outcome = 'Queued' AND reason IS NULL) OR "
            "(outcome = 'Denied' AND reason IS NOT NULL)",
            name="ck_outbound_decisions_reason",
        ),
        # At most one *allowed* decision per intent key, mirroring the Outbox's
        # own uniqueness. Denials repeat freely: refusing the same intent twice
        # is history, not a conflict.
        Index(
            "uq_outbound_decision_queued",
            "idempotency_key",
            unique=True,
            postgresql_where=sql_text("outcome = 'Queued'"),
        ),
        Index("ix_outbound_decisions_lead", "lead_id", "decided_at"),
    )


class AdminMessage(Base):
    """One durably accepted message from the Telegram Administrative Channel.

    Administrative work has its own capacity and does not consume the three
    live-Lead slots (P-037), so it gets its own record rather than sharing the
    WhatsApp Inbox. It still needs durability and idempotency: ``update_id`` is
    Telegram's monotonic identifier and stops a re-polled update from executing
    a Status change twice.

    The row is also what P-065 means by "the originating Inbox message" in the
    audit record for an administrative mutation.
    """

    __tablename__ = "admin_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    chat_id: Mapped[str] = mapped_column(String(40), nullable=False)
    from_user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    from_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # False when the sender is not on the allowlist. The message is still
    # persisted — an unauthorised attempt is exactly the kind of thing the audit
    # trail should show — but it never reaches the Administrative Role.
    authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_update: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ChannelCursor(Base):
    """Where a polled channel has read up to.

    Telegram long-polling is at-least-once: an update is only retired once the
    next poll acknowledges a higher offset. Persisting the cursor means a
    restart resumes rather than replaying the whole backlog.
    """

    __tablename__ = "channel_cursors"

    channel: Mapped[str] = mapped_column(String(40), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AppointmentStatus(str, enum.Enum):
    """P-042. Only CONFIRMED is a Confirmed Appointment."""

    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    REJECTED = "Rejected"
    # Calendar may have accepted the event but the final result is unprovable.
    # Not a Confirmed Appointment, and never retried as a new booking.
    NEEDS_REVIEW = "NeedsReview"
    # A human handled the affected Lead and removed the Calendar event after an
    # Inactive-Property review. It is distinct from a rejected booking attempt.
    CANCELLED = "Cancelled"


class LeadNotificationStatus(str, enum.Enum):
    """How a reconciled appointment outcome reaches the Lead (P-044)."""

    QUEUED = "Queued"
    PENDING_MANUAL = "PendingManual"
    NOTIFIED = "Notified"


class InactiveReviewStatus(str, enum.Enum):
    """The deliberately small P-017/P-018 manual handling path."""

    PENDING = "Pending"
    HANDLING_MANUALLY = "HandlingManually"
    COMPLETE = "Complete"


class AvailabilitySnapshot(Base):
    """Candidate slots observed once, for one Conversation and Property (ADR-0011).

    Durable conversational evidence, not a reservation and not current truth.
    Booking always rechecks the exact interval live. At most one snapshot is
    current per (Conversation, Property); a refresh replaces it.
    """

    __tablename__ = "availability_snapshots"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(60), nullable=False)
    # Every computed interval, as ISO strings. The complete snapshot is retained
    # even though one tool result returns at most six (P-059).
    slots: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "property_uuid", name="uq_snapshot_conversation_property"
        ),
    )


class Appointment(Base):
    """One Appointment Booking Attempt, persisted before Calendar is touched.

    The row exists first so a retry or restart reconciles this same attempt
    rather than issuing a logically new booking (P-042). ``idempotency_key`` is
    derived from trusted state — Conversation, Property, and exact start — never
    from a model-supplied value.
    """

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # The readable reference used in Administrative alerts and tools.
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Display-only, model-supplied, explicitly NOT business truth. Never used
    # for identity, matching, or authorization. See amendment 3 in
    # docs/decisions/checkpoint-3-inputs.md.
    attendee_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AppointmentStatus.PENDING.value
    )
    calendar_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The deterministic Lead-facing message for this outcome — the confirmation
    # or the needs-review notice — released exactly once, through the Outbox.
    lead_notice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A reconciled NeedsReview outcome has a second Lead-notification lifecycle.
    # This cannot share lead_notice_at: the original ambiguity notice and the
    # eventual confirmation/rejection are separate facts (P-044).
    resolution_notification_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    resolution_notification_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Deactivation preserves the appointment and opens a human review. Stage 0
    # supports the accepted "I will handle it" path without a generic workflow
    # engine or direct Calendar-delete tool.
    inactive_review_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Broker notification bookkeeping (amendment 2). Each is sent at most once.
    booked_notice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    digest_sent_on: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview', 'Cancelled')",
            name="ck_appointments_status",
        ),
        CheckConstraint(
            "resolution_notification_status IS NULL OR "
            "resolution_notification_status IN ('Queued', 'PendingManual', 'Notified')",
            name="ck_appointments_resolution_notification",
        ),
        CheckConstraint(
            "inactive_review_status IS NULL OR "
            "inactive_review_status IN ('Pending', 'HandlingManually', 'Complete')",
            name="ck_appointments_inactive_review",
        ),
        Index("ix_appointments_upcoming", "status", "starts_at"),
    )


class AgentSession(Base):
    """Binds a Hermes session to a product Role (trusted context, TC-008).

    The plugin forwards the runtime-supplied ``session_id``; this table is how
    the Product application resolves it to a Role. Identity is therefore never
    accepted as a model argument.

    ``hermes_session_id`` is the value Hermes reports to tool handlers as
    ``session_id`` — the ``stored_session_id`` returned by ``session.create``.
    """

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hermes_session_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    # The gateway-side handle used for prompt.submit / session.steer.
    gateway_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # One persistent Sales session per active Lead Engagement Cycle (P-064).
    # An expired cycle's session is never carried into its successor.
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_engagement_cycles.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    # For an Administrative session, the Telegram chat it serves. One persistent
    # session per administrator, separate from every Sales session (ADR-0001).
    channel_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('Sales', 'Administrative')", name="ck_agent_sessions_role"
        ),
    )
