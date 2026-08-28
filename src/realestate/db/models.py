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
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)

# Aliased: ``InboxMessage.text`` shadows the bare name inside that class body.
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
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


class FactsReviewState(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    NEEDS_REVIEW = "NeedsReview"


class ListingSourceKind(str, enum.Enum):
    ORGANIZATION = "Organization"
    COLLABORATOR = "Collaborator"


class ListingAvailability(str, enum.Enum):
    AVAILABLE = "Available"
    RESERVED = "Reserved"
    SOLD = "Sold"
    RENTED = "Rented"
    TEMPORARILY_UNAVAILABLE = "TemporarilyUnavailable"
    UNKNOWN = "Unknown"


class ListingPublicationState(str, enum.Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    UNPUBLISHED = "Unpublished"


class ListingAuthority(str, enum.Enum):
    AUTHORIZED = "Authorized"
    PENDING = "Pending"
    EXPIRED = "Expired"
    REVOKED = "Revoked"


class ListingOfferOperation(str, enum.Enum):
    SALE = "Sale"
    RENTAL = "Rental"
    PRESALE = "Presale"


class OfferAvailability(str, enum.Enum):
    AVAILABLE = "Available"
    RESERVED = "Reserved"
    COMPLETED = "Completed"
    TEMPORARILY_UNAVAILABLE = "TemporarilyUnavailable"
    WITHDRAWN = "Withdrawn"
    UNKNOWN = "Unknown"


class PublicPriceVisibility(str, enum.Enum):
    VISIBLE = "Visible"
    HIDDEN = "Hidden"


class CatalogPresentationTier(str, enum.Enum):
    LAREVIA = "Larevia"
    PREMIUM = "Premium"
    SUPER_PREMIUM = "SuperPremium"


class WebsiteConversationStatus(str, enum.Enum):
    OPEN = "Open"
    HANDOFF_PENDING = "HandoffPending"
    VERIFIED = "Verified"
    CLOSED = "Closed"


class WebsiteMessageRole(str, enum.Enum):
    CUSTOMER = "Customer"
    MAIA = "Maia"
    SYSTEM = "System"


class ChannelHandoffPurpose(str, enum.Enum):
    CONTINUE_WHATSAPP = "ContinueWhatsApp"
    APPOINTMENT = "Appointment"
    SAVED_COLLECTION_PROTECTION = "SavedCollectionProtection"


class PublicAnalyticsEventName(str, enum.Enum):
    LISTING_IMPRESSION = "ListingImpression"
    GALLERY_OPEN = "GalleryOpen"
    LISTING_SAVED = "ListingSaved"
    MAIA_STARTED = "MaiaStarted"
    HANDOFF_CREATED = "HandoffCreated"
    APPOINTMENT_REQUESTED = "AppointmentRequested"


class ExternalInventoryScope(str, enum.Enum):
    ORGANIZATION = "Organization"
    COLLABORATOR = "Collaborator"


class ExternalCandidateState(str, enum.Enum):
    AUTHORIZED = "Authorized"
    PENDING = "Pending"
    DENIED = "Denied"


class InventorySourceStatus(str, enum.Enum):
    DISABLED = "Disabled"
    NEVER_SYNCED = "NeverSynced"
    HEALTHY = "Healthy"
    PARTIAL = "Partial"
    RATE_LIMITED = "RateLimited"
    FAILED = "Failed"


class RevalidationOutcome(str, enum.Enum):
    ELIGIBLE = "Eligible"
    PENDING = "Pending"
    DENIED = "Denied"


class MessageTemplateStatus(str, enum.Enum):
    """Provider lifecycle observed from the WhatsApp Business Account."""

    APPROVED = "Approved"
    PENDING = "Pending"
    REJECTED = "Rejected"
    PAUSED = "Paused"
    DISABLED = "Disabled"
    DELETED = "Deleted"


class ReactivationCandidateStatus(str, enum.Enum):
    PENDING = "Pending"
    AUTHORIZED = "Authorized"
    REJECTED = "Rejected"
    REVOKED = "Revoked"
    QUEUED = "Queued"
    DENIED = "Denied"
    RESPONDED = "Responded"


class DevelopmentCampaignStatus(str, enum.Enum):
    DRAFT = "Draft"
    ACTIVE = "Active"
    PAUSED = "Paused"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"


class CampaignAudienceStatus(str, enum.Enum):
    INCLUDED = "Included"
    EXCLUDED = "Excluded"
    QUEUED = "Queued"
    DENIED = "Denied"
    RESPONDED = "Responded"


class AgentRole(str, enum.Enum):
    """Separate conversational roles with separate authority (ADR-0001)."""

    SALES = "Sales"
    ADMINISTRATIVE = "Administrative"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # ADR-0019: commercial data belongs to a Brokerage Organization explicitly
    # rather than to an implicit global account.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The readable immutable Property Key from the Markdown (P-048).
    property_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Case-, whitespace- and diacritic-insensitive form; unique across Stage 0.
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PropertyStatus.ACTIVE.value
    )
    inactive_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Private operational data. It is never stored in the Property Document or
    # returned by the ordinary property-information tool.
    visit_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stage 4 physical truth.  Property Documents are immutable provenance;
    # these fields are the catalog's reviewed projection and exclude Offer
    # price/operation, which belong to ``listing_offers``.
    property_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="Other"
    )
    physical_facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    facts_review_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FactsReviewState.PENDING.value
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    facts_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    facts_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    development_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("developments.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("unit_models.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "property_document_versions.id", use_alter=True, name="fk_accepted_version"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
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
        CheckConstraint(
            "facts_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_properties_facts_review",
        ),
        Index("ix_properties_normalized_name", "organization_id", "normalized_name"),
    )


class PropertyDocumentVersion(Base):
    """One immutable accepted document version.

    Rows are append-only. A replacement adds a version and moves the Property's
    accepted-version pointer; it never rewrites an existing row (P-046).
    """

    __tablename__ = "property_document_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
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
    # ADR-0019: commercial data belongs to a Brokerage Organization explicitly
    # rather than to an implicit global account.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The Lead's WhatsApp id as Meta reports it (digits, no '+').
    wa_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    follow_up_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "wa_id", name="uq_leads_org_wa_id"),
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
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
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
    # ADR-0019: commercial data belongs to a Brokerage Organization explicitly
    # rather than to an implicit global account.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
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
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="SET NULL"),
        nullable=True,
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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
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
    # ADR-0026: when the message *body* was expired. The row survives so the
    # commercial record that references it — a trigger id, an attribution, an
    # audit event — does not lose its anchor.
    content_expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        # The retention sweep looks for conversations that still have content.
        # Partial, so it shrinks as bodies expire instead of growing (0014).
        Index(
            "ix_inbox_messages_unexpired",
            "conversation_id",
            "sent_at",
            postgresql_where=sql_text("content_expired_at IS NULL"),
        ),
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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
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
            "status IN ('Processing', 'Settled', 'Failed')",
            name="ck_inbox_groups_status",
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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbox_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbox_groups.id"), nullable=True
    )
    # Idempotency: at most one Outbox row per (group, kind).
    idempotency_key: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False
    )
    to_wa_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    covered_inbox_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutboxStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ADR-0026, as for the Inbox: what Product said expires with the thread,
    # while the eligibility decision that authorised it does not.
    content_expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
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
    # Stage 7 evidence fields. Existing records remain readable, but a real
    # marketing-grant capture path must populate all of them before Product may
    # treat the grant as campaign authority.
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notice_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_locator: Mapped[str | None] = mapped_column(String(240), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
        UUID(as_uuid=True),
        ForeignKey("inbox_messages.id", ondelete="SET NULL"),
        nullable=True,
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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
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
    template_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # When the Meta customer-service window closes, as Product computed it.
    service_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="SET NULL"),
        nullable=True,
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
        # The Inbox's restriction panel. PostgreSQL does not index a foreign
        # key on its own (0014).
        Index(
            "ix_outbound_decisions_conversation",
            "conversation_id",
            sql_text("decided_at DESC"),
        ),
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
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
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
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
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
    # Superseded by a successor appointment that was secured *first*. Never a
    # step on the way to rescheduling: a row only reaches this once the new
    # visit is Confirmed, which is what makes a failed reschedule preserve the
    # original (ADR-0037).
    RESCHEDULED = "Rescheduled"


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
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    horizon_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    time_zone: Mapped[str] = mapped_column(String(60), nullable=False)
    # Whose availability this is (Stage 3). Nullable for snapshots taken before
    # appointments had an owner. Stored so a quote and the booking that follows
    # it cannot silently be about two different people's calendars.
    advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Every computed interval, as ISO strings. The complete snapshot is retained
    # even though one tool result returns at most six (P-059).
    slots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

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
    # ADR-0019: commercial data belongs to a Brokerage Organization explicitly
    # rather than to an implicit global account.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The readable reference used in Administrative alerts and tools.
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(300), unique=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
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
    inactive_review_status: Mapped[str | None] = mapped_column(
        String(24), nullable=True
    )
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

    # -- Stage 3: the visit belongs to an Advisor -------------------------
    #
    # Nullable only because Stage 0 and Stage 2 rows exist. Every appointment
    # booked from now on has one, and ``Appointments`` refuses to confirm
    # without it: a confirmed visit nobody owns is exactly the failure this
    # stage exists to remove (PROJECT_MEMORY, ADR-0048).
    advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Set only when somebody *other than* the owner conducts the visit, which
    # PROJECT_MEMORY requires to be explicit. NULL means the owner conducts it;
    # it never means "unknown".
    conducting_advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # The calendar the event was written to, captured at booking. Recovery must
    # look for the event where it was actually created, not wherever the
    # Advisor's configuration points today.
    calendar_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    @property
    def attending_advisor_id(self) -> uuid.UUID | None:
        """Whoever will actually be at the property (ADR-0048).

        Not a null-coalesce spelled out at each caller: it is the rule that a
        named conductor supersedes the owner for everything about being there —
        the calendar the event lands on, the reminder, the notice. Written once
        so a third role could not be added to five of six places.
        """
        return self.conducting_advisor_id or self.advisor_id
    # The commercial pursuit this visit belongs to, when there is one.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Atomic rescheduling (ADR-0037): the successor is secured first, then this
    # row points at it. Both directions are kept because the operator asks both
    # questions — "what replaced this?" and "what did this replace?".
    rescheduled_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # What the Advisor recorded afterwards. ``attendance`` is the fact, and it
    # is only ever written by a human: Product never infers that a visit
    # happened from the clock (ADR-0037, SAN-038).
    attendance: Mapped[str | None] = mapped_column(String(12), nullable=True)
    attendance_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attendance_recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    visit_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A Missed Appointment produces a Maia rescheduling invitation only when the
    # Advisor explicitly authorises one (ADR-0037). Default false, so silence
    # never becomes permission.
    reschedule_invitation_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview', "
            "'Cancelled', 'Rescheduled')",
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
        CheckConstraint(
            "attendance IS NULL OR attendance IN ('Attended', 'Missed')",
            name="ck_appointments_attendance",
        ),
        # Attendance is a human record: the fact and its author arrive together.
        CheckConstraint(
            "(attendance IS NULL) = (attendance_recorded_by IS NULL)",
            name="ck_appointments_attendance_author",
        ),
        # Only a Missed visit can authorise a rescheduling invitation, and only
        # after somebody recorded the miss.
        CheckConstraint(
            "reschedule_invitation_authorized IS FALSE OR attendance = 'Missed'",
            name="ck_appointments_reschedule_invitation",
        ),
        Index("ix_appointments_upcoming", "status", "starts_at"),
        Index("ix_appointments_advisor", "advisor_id", "starts_at"),
        # Availability asks for one calendar over a window as two inequalities,
        # a shape the GiST exclusion below cannot serve.
        Index("ix_appointments_calendar", "calendar_id", "starts_at"),
        Index(
            "uq_appointments_active_reschedule",
            "rescheduled_from_id",
            unique=True,
            postgresql_where=sql_text(
                "rescheduled_from_id IS NOT NULL AND status <> 'Rejected'"
            ),
        ),
        ExcludeConstraint(  # type: ignore[no-untyped-call]
            ("calendar_id", "="),
            (func.tstzrange(starts_at, ends_at, "[)"), "&&"),
            where=sql_text(
                "calendar_id IS NOT NULL AND ("
                "status IN ('Pending', 'Confirmed', 'NeedsReview') OR "
                "(status = 'Rescheduled' AND calendar_event_id IS NOT NULL))"
            ),
            using="gist",
            name="ex_appointments_calendar_overlap",
        ),
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
    hermes_session_id: Mapped[str] = mapped_column(
        String(120), unique=True, nullable=False
    )
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


# ==========================================================================
# Stage 2 — the commercial system of record (ADR-0019, ADR-0022, ADR-0023,
# ADR-0031, ADR-0032, ADR-0026)
#
# Four separations carry this section, and every table below exists to keep one
# of them honest:
#
# * an **Organization** owns commercial data, so nothing here is implicitly
#   global (ADR-0019);
# * a **Contact** is a person across time, distinct from the channel identity
#   Meta authenticates and from the Conversation they happen to be having;
# * a **commercial stage** says where the pursuit stands and nothing else —
#   assignment, appointments, consent and Do Not Contact are their own state;
# * an **inferred criterion** is Pending until the Contact confirms it, so
#   probabilistic interpretation never silently becomes qualification evidence
#   (ADR-0031).
# ==========================================================================

# ADR-0026: a Property Need not confirmed for this long is Stale and may only
# identify a possible reactivation, never current customer truth. The same
# period governs when conversation *content* expires; the two are deliberately
# separate mechanisms that happen to share a number today.
PROPERTY_NEED_STALE_DAYS = 90
CONVERSATION_CONTENT_RETENTION_DAYS = 90

# The slug of the Brokerage Organization the migration creates. Larevia is the
# documented working brand (CONTEXT.md), not customer data.
LAREVIA_SLUG = "larevia"


class MemberRole(str, enum.Enum):
    """The MVP's two product roles (PROJECT_MEMORY, ADR-0018).

    Authority follows the role: an Administrator sees the whole operation, an
    Advisor sees their organization and their own assignments. Eligibility to
    *own* an Opportunity is a separate flag, because Santiago initially holds
    both roles and a role enumeration that tried to express that would stop
    being unambiguous.
    """

    ADMINISTRATOR = "OrganizationAdministrator"
    ADVISOR = "RealEstateAdvisor"


class MemberProvisioning(str, enum.Enum):
    """Who owns a member row: configuration, or an Administrator.

    Startup reconciliation deactivates a login that has left the configuration.
    Once an Administrator can add Advisors through the team surface, applying
    that rule to *every* row would delete the team on the next restart, so the
    provenance is stored (ADR-0047).
    """

    CONFIGURATION = "Configuration"
    ADMINISTRATOR = "Administrator"


class ChannelIdentityTrust(str, enum.Enum):
    """How well Product knows that a channel identity is who it claims to be.

    ``Verified`` means the platform authenticated it — a signed Meta webhook
    carrying ``from.wa_id``. ``Asserted`` means a human or a form typed it.
    Only a Verified identity may deduplicate a Contact automatically.
    """

    VERIFIED = "Verified"
    ASSERTED = "Asserted"


class TransactionIntent(str, enum.Enum):
    """What the Contact is trying to do. Unknown until stated, never guessed."""

    BUY = "Buy"
    RENT = "Rent"
    SELL = "Sell"
    LEASE_OUT = "LeaseOut"


class PropertyNeedStatus(str, enum.Enum):
    """Whether a Property Need may be used as current commercial truth."""

    ACTIVE = "Active"
    STALE = "Stale"


class CriterionState(str, enum.Enum):
    """ADR-0031: an inferred value is Pending until the Contact confirms it."""

    CONFIRMED = "Confirmed"
    PENDING = "Pending"


class CriterionSource(str, enum.Enum):
    """Where a criterion's value came from. Provenance is retained, not folded."""

    CONTACT_STATED = "ContactStated"
    MODEL_INFERRED = "ModelInferred"
    ADVISOR_RECORDED = "AdvisorRecorded"


class OpportunityKind(str, enum.Enum):
    """Demand versus Listing Acquisition (CONTEXT.md).

    Both are bounded commercial pursuits with the same stages, an owner and an
    outcome, so they share this table. What differs is who wants what, and in
    the MVP a Listing Acquisition is qualified and handed to the Administrator.
    """

    DEMAND = "Demand"
    LISTING_ACQUISITION = "ListingAcquisition"


class OpportunityStage(str, enum.Enum):
    """The commercial pipeline, and only the commercial pipeline.

    Assignment, appointments, consent and Do Not Contact are deliberately absent:
    a suppressed Contact is not Lost, an Opportunity with no Advisor is not a
    stage, and a cancelled appointment does not move anything here (ADR-0037).
    """

    NEW = "New"
    IN_CONVERSATION = "InConversation"
    QUALIFIED = "Qualified"
    SEARCHING = "Searching"
    VISITING = "Visiting"
    NEGOTIATING = "Negotiating"
    WON = "Won"
    LOST = "Lost"
    DORMANT = "Dormant"


#: Stages an Opportunity can still be worked in. Won and Lost are terminal;
#: Dormant is paused and can be legitimately reconsidered, so it is neither
#: active nor closed.
ACTIVE_STAGES: frozenset[str] = frozenset(
    {
        OpportunityStage.NEW.value,
        OpportunityStage.IN_CONVERSATION.value,
        OpportunityStage.QUALIFIED.value,
        OpportunityStage.SEARCHING.value,
        OpportunityStage.VISITING.value,
        OpportunityStage.NEGOTIATING.value,
    }
)

#: Stages that mean the minimum qualification criteria were accepted. Once
#: Qualified, an Opportunity does not become "unqualified" by advancing.
QUALIFIED_OR_BEYOND: frozenset[str] = frozenset(
    {
        OpportunityStage.QUALIFIED.value,
        OpportunityStage.SEARCHING.value,
        OpportunityStage.VISITING.value,
        OpportunityStage.NEGOTIATING.value,
    }
)


class OpportunityOriginSource(str, enum.Enum):
    """The first known commercial provenance of an Opportunity."""

    WHATSAPP_INBOUND = "WhatsAppInbound"
    WEBSITE_CONVERSATION = "WebsiteConversation"
    REFERRAL = "Referral"
    CAMPAIGN = "Campaign"
    ADVISOR_ENTRY = "AdvisorEntry"
    LEGACY_BACKFILL = "LegacyBackfill"


class AssignmentBasis(str, enum.Enum):
    """Why this Advisor owns this Opportunity.

    Deterministic and recorded, so "who decided this" never has to be guessed
    from timestamps. ``PropertyExpert`` is declared but unreachable in Stage 2:
    the Property Expert designation itself arrives with the human-operation
    cut, and naming the basis now is what keeps the rule from being rewritten
    then.
    """

    PRESERVED = "Preserved"
    PROPERTY_EXPERT = "PropertyExpert"
    #: A backup expert, because the primary one is absent or ineligible. Kept
    #: distinct from ``PROPERTY_EXPERT`` so "the specialist took it" and "the
    #: specialist could not" are different recorded facts.
    PROPERTY_EXPERT_BACKUP = "ExpertBackup"
    DEFAULT_ADVISOR = "DefaultAdvisor"
    MANUAL_ADMIN = "ManualAdmin"


class AssignmentQueueReason(str, enum.Enum):
    """Why an Opportunity could not be assigned deterministically."""

    NO_ELIGIBLE_ADVISOR = "NoEligibleAdvisor"
    DEFAULT_ADVISOR_INACTIVE = "DefaultAdvisorInactive"
    #: Everybody the deterministic rule would have chosen has a current
    #: Advisor Absence. Separate from "inactive" because the remedy differs: an
    #: absence ends, a deactivated login has to be reinstated or replaced.
    EVERY_CANDIDATE_ABSENT = "EveryCandidateAbsent"


class NextActionKind(str, enum.Enum):
    """What is owed. Calls are human work recorded here, not automated."""

    QUALIFY = "Qualify"
    CALL = "Call"
    WHATSAPP_MESSAGE = "WhatsAppMessage"
    SEND_LISTINGS = "SendListings"
    SCHEDULE_VISIT = "ScheduleVisit"
    VISIT_FOLLOW_UP = "VisitFollowUp"
    DOCUMENT_REVIEW = "DocumentReview"
    OTHER = "Other"


class NextActionStatus(str, enum.Enum):
    """Pending is the only status that discharges the coverage promise."""

    PENDING = "Pending"
    COMPLETED = "Completed"
    SUPERSEDED = "Superseded"
    CANCELLED = "Cancelled"


class NextActionOutcome(str, enum.Enum):
    """What happened when the action was completed. Required on completion."""

    DONE = "Done"
    NO_ANSWER = "NoAnswer"
    RESCHEDULED = "Rescheduled"
    NOT_INTERESTED = "NotInterested"
    BLOCKED = "Blocked"


class OpportunityExceptionReason(str, enum.Enum):
    """Why an active Opportunity legitimately has no Next Action right now.

    The coverage promise is "a Next Action **or** an auditable exception". This
    is that exception: explicit, attributed, and clearable, rather than a silent
    gap that a report has to interpret.
    """

    AWAITING_CONTACT = "AwaitingContact"
    CONTACT_UNREACHABLE = "ContactUnreachable"
    DO_NOT_CONTACT = "DoNotContact"
    OUT_OF_SERVICE_AREA = "OutOfServiceArea"
    ADMIN_REVIEW = "AdminReview"


class Organization(Base):
    """The Brokerage Organization that owns commercial data (ADR-0019).

    One row exists in Stage 2 and that is deliberate: ADR-0018 builds the
    brokerage before the platform. What matters is that every commercial record
    names it explicitly, so a second organization is a data question rather
    than a rewrite of every query.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrganizationMember(Base):
    """One authorized human inside an Organization.

    ``login`` is the HTTP Basic username the existing operational surface
    already authenticates. Authentication is unchanged; what is new is that
    *authorization* now resolves that username to a row with an explicit
    Organization and role. A username that authenticates but has no member row
    is refused rather than treated as an implicit administrator.
    """

    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    login: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    # Whether this member may be the Responsible Advisor for an Opportunity.
    # Separate from ``role`` so one person can administer and also advise.
    advises: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The deterministic fallback of the assignment rule (PROJECT_MEMORY): at
    # most one per Organization, enforced by a partial unique index.
    is_default_advisor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Who created this member, and therefore who may overwrite it. Startup
    # reconciliation is the bootstrap and must not deactivate somebody an
    # Administrator added through the team surface (ADR-0047), so the two
    # provenances are recorded rather than inferred from whether a login
    # happens to appear in configuration today.
    provisioned_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MemberProvisioning.ADMINISTRATOR.value
    )
    # The Advisor's authoritative calendar (ADR-0048). An Advisor without one
    # has no availability Product may quote and cannot receive an appointment;
    # that is a refusal, never an empty schedule treated as free.
    calendar_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Where this member's immediate operational alerts go. Optional: an Advisor
    # without one still gets the durable CRM alert, and the Administrator is
    # told the immediate notice could not be delivered.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('OrganizationAdministrator', 'RealEstateAdvisor')",
            name="ck_organization_members_role",
        ),
        CheckConstraint(
            "provisioned_by IN ('Configuration', 'Administrator')",
            name="ck_organization_members_provisioned_by",
        ),
        # An Advisor who cannot own Opportunities is not an Advisor.
        CheckConstraint(
            "role <> 'RealEstateAdvisor' OR advises IS TRUE",
            name="ck_organization_members_advisor_advises",
        ),
        CheckConstraint(
            "is_default_advisor IS FALSE OR advises IS TRUE",
            name="ck_organization_members_default_advises",
        ),
        UniqueConstraint("login", name="uq_organization_members_login"),
        Index(
            "uq_organization_default_advisor",
            "organization_id",
            unique=True,
            postgresql_where=sql_text("is_default_advisor IS TRUE"),
        ),
        Index("ix_organization_members_org", "organization_id", "role"),
    )


class Contact(Base):
    """A person known to the operation across time (CONTEXT.md).

    Not a Lead, not a phone number and not a Conversation. A Contact survives
    the expiry of every message they ever sent, can hold several Property Needs
    and Opportunities at once, and can be reachable through more than one
    channel identity.
    """

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The best name Product actually knows. A WhatsApp profile name is a claim
    # by the sender, so it is stored as a display hint and never as legal
    # identity. NULL is a legitimate value: an anonymous inquiry has no name.
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_contacts_org", "organization_id", "created_at"),)


class ContactChannelIdentity(Base):
    """One addressable identity through which a Contact reaches the operation.

    This is the join that keeps Contact separate from channel identity. The
    WhatsApp row points at the existing ``leads`` record, which is what Meta
    authenticates and what the Outbound Eligibility Gate already reasons about;
    nothing about Stage 1's consent, suppression or window rules moves here.

    Two identities are the same person only when the *same* trusted identifier
    is presented again. Similar-looking numbers are never merged: in Mexico the
    difference between ``52`` and ``521`` prefixes is exactly the kind of
    plausible-but-unproven equivalence that would silently join two people's
    commercial histories.
    """

    __tablename__ = "contact_channel_identities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="WhatsApp")
    # The channel-native identifier, exactly as the platform reported it.
    identity: Mapped[str] = mapped_column(String(120), nullable=False)
    trust: Mapped[str] = mapped_column(String(12), nullable=False)
    # The WhatsApp channel identity record this row corresponds to, when the
    # channel is WhatsApp. Kept as a real foreign key so Stage 1's Lead-scoped
    # suppression and consent evidence stays reachable from the Contact.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("channel = 'WhatsApp'", name="ck_contact_identity_channel"),
        CheckConstraint(
            "trust IN ('Verified', 'Asserted')", name="ck_contact_identity_trust"
        ),
        CheckConstraint(
            "channel <> 'WhatsApp' OR lead_id IS NOT NULL",
            name="ck_contact_identity_whatsapp_lead",
        ),
        UniqueConstraint(
            "organization_id", "channel", "identity", name="uq_contact_identity"
        ),
        # One Contact per WhatsApp channel identity. Merging two Contacts is a
        # deliberate later decision, not something a second webhook can cause.
        UniqueConstraint("lead_id", name="uq_contact_identity_lead"),
        Index("ix_contact_identities_contact", "contact_id"),
    )


class PropertyNeed(Base):
    """One Contact's coherent real-estate intent and constraints.

    Confirmed criteria and Pending ones live in
    :class:`PropertyNeedCriterion`; this row holds what the need *is* and
    whether it may still be treated as current truth. ``last_confirmed_at`` is
    the only input to staleness, so a need that is merely discussed does not
    refresh itself.
    """

    __tablename__ = "property_needs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL until the Contact states it. An inferred intent is a Pending
    # criterion, not a value here.
    transaction_intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PropertyNeedStatus.ACTIVE.value
    )
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    became_stale_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_intent IS NULL OR "
            "transaction_intent IN ('Buy', 'Rent', 'Sell', 'LeaseOut')",
            name="ck_property_needs_intent",
        ),
        CheckConstraint(
            "status IN ('Active', 'Stale')", name="ck_property_needs_status"
        ),
        CheckConstraint(
            "(status = 'Stale') = (became_stale_at IS NOT NULL)",
            name="ck_property_needs_stale_stamp",
        ),
        Index("ix_property_needs_contact", "contact_id", "created_at"),
        Index("ix_property_needs_staleness", "status", "last_confirmed_at"),
    )


class PropertyNeedCriterion(Base):
    """One constraint of a Property Need, with provenance and confirmation state.

    Append-only per name: confirming or changing a criterion supersedes the
    previous row instead of overwriting it, so "Maia inferred 3 recámaras and
    the Contact later said 2" stays legible. The partial unique index makes the
    current value of each named criterion singular.
    """

    __tablename__ = "property_need_criteria"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_need_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_needs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('Confirmed', 'Pending')", name="ck_need_criteria_state"
        ),
        CheckConstraint(
            "source IN ('ContactStated', 'ModelInferred', 'AdvisorRecorded')",
            name="ck_need_criteria_source",
        ),
        CheckConstraint(
            "(state = 'Confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_need_criteria_confirmed_stamp",
        ),
        Index(
            "uq_need_criterion_current",
            "property_need_id",
            "name",
            unique=True,
            postgresql_where=sql_text("superseded_at IS NULL"),
        ),
    )


class Opportunity(Base):
    """One bounded commercial pursuit (CONTEXT.md, ADR-0032).

    The stage says where the pursuit stands. The Responsible Advisor, the
    appointment, the consent state and any communication restriction are all
    elsewhere on purpose: overloading them into one enumeration is how CRMs end
    up unable to say whether "Closed" meant sold, silent or forbidden.

    Terminal evidence is required rather than inferred. ``Lost`` needs a reason
    (``Unknown`` is an allowed, explicit one), ``Dormant`` needs the condition
    under which it may be reconsidered, and ``Won`` needs accepted operational
    evidence recorded by an Administrator — a visit or an offer is not one.
    """

    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_need_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_needs.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OpportunityStage.NEW.value
    )
    # Denormalised from the open ``opportunity_assignments`` row so the CRM's
    # list queries do not need a correlated subquery per row. The assignment
    # table stays the history; this column is maintained only by the Assignment
    # module, inside the same transaction.
    responsible_advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    qualified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lost_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dormant_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    dormant_revisit_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    won_evidence: Mapped[str | None] = mapped_column(String(60), nullable=True)
    won_evidence_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    won_recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('Demand', 'ListingAcquisition')", name="ck_opportunities_kind"
        ),
        CheckConstraint(
            "stage IN ('New', 'InConversation', 'Qualified', 'Searching', "
            "'Visiting', 'Negotiating', 'Won', 'Lost', 'Dormant')",
            name="ck_opportunities_stage",
        ),
        CheckConstraint(
            "stage <> 'Lost' OR lost_reason IS NOT NULL",
            name="ck_opportunities_lost_reason",
        ),
        CheckConstraint(
            "stage <> 'Dormant' OR dormant_reason IS NOT NULL",
            name="ck_opportunities_dormant_reason",
        ),
        CheckConstraint(
            "stage <> 'Won' OR "
            "(won_evidence IS NOT NULL AND won_recorded_by IS NOT NULL)",
            name="ck_opportunities_won_evidence",
        ),
        # Qualified is not a label an Advisor can apply without the criteria
        # having been accepted at a known moment.
        CheckConstraint(
            "stage NOT IN ('Qualified', 'Searching', 'Visiting', 'Negotiating') "
            "OR qualified_at IS NOT NULL",
            name="ck_opportunities_qualified_stamp",
        ),
        Index("ix_opportunities_org_stage", "organization_id", "stage"),
        Index("ix_opportunities_advisor", "responsible_advisor_id", "stage"),
        Index("ix_opportunities_contact", "contact_id", "created_at"),
        # The dormancy sweep filters on these two; the pipeline surface sorts
        # on the second. Without them both were sequential scans (0014).
        Index("ix_opportunities_activity", "stage", "last_activity_at"),
        Index(
            "ix_opportunities_org_activity",
            "organization_id",
            sql_text("last_activity_at DESC"),
        ),
    )


class CommercialTransaction(Base):
    """The completed deal produced by one Won Opportunity (ADR-0032).

    This is deliberately not an Opportunity outcome column. It is the separate
    commercial record to which property, participants, price, attribution and
    commission facts can be added without turning the pursuit into the deal.
    Stage 2 records only evidence Product actually has.
    """

    __tablename__ = "commercial_transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    property_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=True,
    )
    evidence: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_detail: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    command_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "evidence IN ('CompletedSale', 'SignedRentalAgreement', "
            "'AcceptedBindingPresale')",
            name="ck_commercial_transactions_evidence",
        ),
        Index(
            "ix_commercial_transactions_org_completed",
            "organization_id",
            "completed_at",
        ),
    )


class OpportunityOrigin(Base):
    """The first known commercial provenance of an Opportunity — write once.

    ADR-0023's attribution promise is that later interactions never overwrite
    the first known source. That is enforced structurally: one row per
    Opportunity, inserted with ``ON CONFLICT DO NOTHING``, and no code path that
    updates it. A newer channel becomes an interaction, not a new origin.
    """

    __tablename__ = "opportunity_origins"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(120), nullable=True)
    advertisement: Mapped[str | None] = mapped_column(String(120), nullable=True)
    referral: Mapped[str | None] = mapped_column(String(200), nullable=True)
    property_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The inbound message that started it, when there was one. SET NULL rather
    # than CASCADE: retention may remove the message, and losing the attribution
    # with it is precisely the failure this table prevents.
    first_inbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inbox_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('WhatsAppInbound', 'WebsiteConversation', 'Referral', "
            "'Campaign', 'AdvisorEntry', 'LegacyBackfill')",
            name="ck_opportunity_origins_source",
        ),
    )


class OpportunityStageTransition(Base):
    """Append-only history of one Opportunity's stage changes.

    ``command_key`` is the idempotency arbiter: the same command replayed after
    a timeout records nothing new and reports the original outcome. It doubles
    as the audit trail an operator reads, which is why the actor is stored here
    rather than only in ``audit_events``.
    """

    __tablename__ = "opportunity_stage_transitions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    command_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_stage_transitions_opportunity", "opportunity_id", "occurred_at"),
    )


class OpportunityAssignment(Base):
    """One period during which an Advisor was responsible for an Opportunity.

    Closed with ``unassigned_at`` rather than deleted, because "who owned this
    in March" is an attribution question the operation will ask. The partial
    unique index is what makes two concurrent assignments resolve to one
    Responsible Advisor instead of two.
    """

    __tablename__ = "opportunity_assignments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    advisor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "basis IN ('Preserved', 'PropertyExpert', 'ExpertBackup', "
            "'DefaultAdvisor', 'ManualAdmin')",
            name="ck_opportunity_assignments_basis",
        ),
        Index(
            "uq_assignment_open",
            "opportunity_id",
            unique=True,
            postgresql_where=sql_text("unassigned_at IS NULL"),
        ),
        Index("ix_assignments_advisor", "advisor_id", "assigned_at"),
    )


class AssignmentQueueEntry(Base):
    """One recorded failure to assign an Opportunity deterministically.

    The Assignment Queue an Administrator works is derived — Opportunities with
    no open assignment — so it cannot drift out of step with the assignment
    table. This row exists to answer *why* the automatic rule produced nothing,
    which a derived set cannot say.
    """

    __tablename__ = "assignment_queue_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "reason IN ('NoEligibleAdvisor', 'DefaultAdvisorInactive', "
            "'EveryCandidateAbsent')",
            name="ck_assignment_queue_reason",
        ),
        # One open entry per Opportunity, so repeated assignment attempts do not
        # accumulate duplicates in the Administrator's queue.
        Index(
            "uq_assignment_queue_open",
            "opportunity_id",
            unique=True,
            postgresql_where=sql_text("resolved_at IS NULL"),
        ),
    )


class NextAction(Base):
    """The specific future action owed for an active Opportunity.

    At most one is Pending at a time, enforced by a partial unique index. That
    single constraint is what gives "substituted" a meaning: scheduling a new
    action closes the previous one as ``Superseded`` in the same transaction,
    and two concurrent schedules cannot both survive.
    """

    __tablename__ = "next_actions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    responsible_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=NextActionStatus.PENDING.value
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    command_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    completion_command_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("next_actions.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('Qualify', 'Call', 'WhatsAppMessage', 'SendListings', "
            "'ScheduleVisit', 'VisitFollowUp', 'DocumentReview', 'Other')",
            name="ck_next_actions_kind",
        ),
        CheckConstraint(
            "status IN ('Pending', 'Completed', 'Superseded', 'Cancelled')",
            name="ck_next_actions_status",
        ),
        # A completed action without a result is the gap the coverage metric is
        # supposed to expose, so the database refuses to record one.
        CheckConstraint(
            "(status = 'Completed') = (outcome IS NOT NULL)",
            name="ck_next_actions_outcome",
        ),
        CheckConstraint(
            "(status = 'Completed') = (completed_at IS NOT NULL)",
            name="ck_next_actions_completed_stamp",
        ),
        Index(
            "uq_next_action_pending",
            "opportunity_id",
            unique=True,
            postgresql_where=sql_text("status = 'Pending'"),
        ),
        Index("ix_next_actions_due", "organization_id", "status", "due_at"),
        Index("ix_next_actions_member", "responsible_member_id", "status", "due_at"),
    )


class OpportunityException(Base):
    """Why an active Opportunity legitimately has no Next Action right now.

    The alternative to this table is a coverage report full of unexplained
    gaps. An exception is explicit, attributed, and clears when the reason
    stops applying.
    """

    __tablename__ = "opportunity_exceptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    command_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "reason IN ('AwaitingContact', 'ContactUnreachable', 'DoNotContact', "
            "'OutOfServiceArea', 'AdminReview')",
            name="ck_opportunity_exceptions_reason",
        ),
        Index(
            "uq_opportunity_exception_open",
            "opportunity_id",
            unique=True,
            postgresql_where=sql_text("cleared_at IS NULL"),
        ),
    )


class CommercialCommandReceipt(Base):
    """Durable idempotency receipt for commercial mutations.

    Some commands update existing rows instead of inserting a naturally unique
    record (confirming a criterion, clearing an exception, or releasing an
    assignment).  Their request key therefore needs its own transactional
    authority rather than an in-memory or router-only check.
    """

    __tablename__ = "commercial_command_receipts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    command_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "command_key", name="uq_commercial_command_org_key"
        ),
        Index(
            "ix_commercial_command_subject",
            "organization_id",
            "subject_type",
            "subject_id",
        ),
    )


# ==========================================================================
# Stage 3 — human operation, team and visits (ADR-0029, ADR-0037, ADR-0047,
# ADR-0048)
#
# Four separations carry this section:
#
# * **expert is not owner.** A Property Expert is a specialist for a Property;
#   a Responsible Advisor is accountable for one Opportunity. Conflating them
#   would silently move ownership every time inventory changed hands.
# * **absence blocks new work, never existing work.** A declared Advisor
#   Absence removes somebody from the assignment rule and from new bookings. It
#   does not reassign an Opportunity or cancel a visit (PROJECT_MEMORY).
# * **handling authority is singular and explicit.** Exactly one of Maia or one
#   human may answer a Contact, and the transition is recorded rather than
#   inferred from who typed last (ADR-0029).
# * **internal alerts are not customer messages.** They ride their own durable
#   channel, so the 15-minute escalation is idempotent across restarts without
#   ever touching the Outbound Eligibility Gate (ADR-0045).
# ==========================================================================


class PropertyExpertRole(str, enum.Enum):
    """Primary specialist, or a backup for when the primary cannot take it."""

    PRIMARY = "Primary"
    BACKUP = "Backup"


class HandlingMode(str, enum.Enum):
    """Who may answer this Contact right now (CONTEXT.md, ADR-0029).

    ``MAIA`` is the default and the only mode in which the Lead worker may
    release a draft. ``HUMAN`` names a holder and pauses Maia. ``AWAITING_``
    ``CONTACT`` is the operation having said its part and waiting. ``ADMIN_``
    ``REVIEW`` is the state a supervisor has to clear, and Maia does not
    converse in it either.
    """

    MAIA = "Maia"
    HUMAN = "Human"
    AWAITING_CONTACT = "AwaitingContact"
    ADMIN_REVIEW = "AdminReview"


#: Modes in which Maia may compose and release a reply. Spelled as a set rather
#: than ``mode == MAIA`` so a fifth mode has to decide explicitly whether Maia
#: speaks in it.
MAIA_MAY_REPLY: frozenset[str] = frozenset({HandlingMode.MAIA.value})


class HandoffStatus(str, enum.Enum):
    """The lifecycle of one request for a human."""

    PENDING = "Pending"
    ACKNOWLEDGED = "Acknowledged"
    #: Withdrawn without a human taking it — the Contact resolved it with Maia,
    #: or an Administrator closed it. Never used to hide an unhandled request.
    CANCELLED = "Cancelled"


class HandoffSource(str, enum.Enum):
    """Why a human is needed. Recorded because the three read differently."""

    #: The Contact asked for a person.
    CONTACT_REQUEST = "ContactRequest"
    #: Deterministic post-appointment routing sent this message to the Advisor
    #: because it was not clearly Appointment Logistics (ADR-0037).
    POST_HANDOFF_ROUTING = "PostHandoffRouting"
    #: A human decided to take over without being asked.
    HUMAN_INITIATED = "HumanInitiated"


class InternalAlertStatus(str, enum.Enum):
    """Delivery state of one internal operational notice."""

    PENDING = "Pending"
    SENT = "Sent"
    #: There is nowhere to deliver it — the recipient has no configured chat.
    #: The alert still exists and is still visible in the CRM.
    UNDELIVERABLE = "Undeliverable"
    FAILED = "Failed"


class InternalAlertKind(str, enum.Enum):
    """What an internal alert is about."""

    HUMAN_HANDOFF_REQUESTED = "HumanHandoffRequested"
    HUMAN_HANDOFF_ESCALATED = "HumanHandoffEscalated"
    APPOINTMENT_ADVISOR_REVIEW = "AppointmentAdvisorReview"
    ABSENCE_REVIEW = "AbsenceReview"
    #: One addressed notice could not be delivered, so the Administrators are
    #: told it could not (ADR-0049).
    ALERT_UNDELIVERABLE = "AlertUndeliverable"


class AppointmentAttendance(str, enum.Enum):
    """Whether the visit happened. Only an Advisor may say (SAN-038)."""

    ATTENDED = "Attended"
    MISSED = "Missed"


class AppointmentReminderKind(str, enum.Enum):
    """The named reminders of the current unvalidated hypothesis (SAN-036).

    The rows are created deterministically so the schedule is inspectable, and
    dispatch stays blocked until Santiago validates the cadence. A reminder
    Product cannot justify is not sent.
    """

    DAY_BEFORE = "DayBefore"
    DAY_OF = "DayOf"


class AdvisorAbsence(Base):
    """A declared period in which an Advisor takes no new work.

    Only an Organization Administrator records or ends one (PROJECT_MEMORY,
    SAN-035). Ending an absence that is already under way truncates it —
    ``ends_at`` moves to the moment it ended — rather than deleting it, because
    "why was this Opportunity queued last Tuesday" has to stay answerable.
    Ending one that has not started yet voids it through ``cancelled_at``.

    Migration 0018 adds a PostgreSQL exclusion constraint so two overlapping
    live absences for one Advisor cannot exist even under concurrency.
    """

    __tablename__ = "advisor_absences"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    advisor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_early_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_advisor_absence_period"),
        CheckConstraint(
            "ended_by IS NOT NULL OR (ended_early_at IS NULL AND cancelled_at IS NULL)",
            name="ck_advisor_absence_ended_by",
        ),
        Index("ix_advisor_absences_advisor", "advisor_id", "starts_at"),
        Index("ix_advisor_absences_org", "organization_id", "starts_at"),
    )

    def covers(self, moment: datetime) -> bool:
        """Whether this absence is in force at *moment*."""
        return (
            self.cancelled_at is None
            and self.starts_at <= moment < self.ends_at
        )


class PropertyExpert(Base):
    """A Real Estate Advisor designated as a Property's specialist.

    Distinct from the Responsible Advisor by construction: this row names a
    *Property*, and nothing here changes who owns an Opportunity. Revoked
    rather than deleted so an attribution question about a past visit still has
    an answer.
    """

    __tablename__ = "property_experts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    advisor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Order among backups. The primary is always 0.
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    designated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    designated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("role IN ('Primary', 'Backup')", name="ck_property_expert_role"),
        CheckConstraint(
            "(role = 'Primary') = (rank = 0)", name="ck_property_expert_rank"
        ),
        # One live primary per Property, and one live designation per person per
        # Property. Both are the database's job: an Administrator double-
        # clicking must not produce two primaries.
        Index(
            "uq_property_expert_primary",
            "property_uuid",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL AND role = 'Primary'"),
        ),
        Index(
            "uq_property_expert_live",
            "property_uuid",
            "advisor_id",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
        Index("ix_property_experts_advisor", "advisor_id"),
    )


class ConversationHandlingState(Base):
    """Who is answering one Conversation, and since when (ADR-0029).

    One row per Conversation, created lazily: an absent row means Maia, which
    is the default the whole product already behaved as. ``version`` makes a
    lost update visible instead of silent — two Advisors pressing *Atender* at
    the same instant resolve to one holder.
    """

    __tablename__ = "conversation_handling"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=HandlingMode.MAIA.value
    )
    holder_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: Why the mode changed, in the product's own vocabulary. Operator-visible.
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('Maia', 'Human', 'AwaitingContact', 'AdminReview')",
            name="ck_conversation_handling_mode",
        ),
        # A human mode with no human is the ambiguity this table removes.
        CheckConstraint(
            "(mode = 'Human') = (holder_member_id IS NOT NULL)",
            name="ck_conversation_handling_holder",
        ),
    )


class HumanHandoffRequest(Base):
    """One unmet request for a human on one Conversation (ADR-0029).

    The 15-minute escalation is a stamped column rather than a scheduled job:
    the alert and its stamp land in one transaction, so a restart mid-window
    re-derives exactly the same due set and cannot alert twice.
    """

    __tablename__ = "human_handoff_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The Advisor alerted immediately. NULL when nobody is responsible yet,
    #: which is itself why the Administrator has to see it.
    advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(14), nullable=False, default=HandoffStatus.PENDING.value
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: When the Administrator must be told if nobody has taken it.
    escalate_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    advisor_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    admin_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: The inbound message that asked, when there was one. Kept so the request
    #: can be read back to an operator even after content expiry blanks bodies.
    trigger_inbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbox_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('ContactRequest', 'PostHandoffRouting', 'HumanInitiated')",
            name="ck_handoff_source",
        ),
        CheckConstraint(
            "status IN ('Pending', 'Acknowledged', 'Cancelled')",
            name="ck_handoff_status",
        ),
        CheckConstraint(
            "(status = 'Pending') = (resolved_at IS NULL)",
            name="ck_handoff_resolution",
        ),
        # One open request per Conversation. A Contact asking three times in a
        # row is one unmet request, not three alerts.
        Index(
            "uq_handoff_open",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text("status = 'Pending'"),
        ),
        Index("ix_handoff_escalation", "status", "escalate_at"),
    )


class InternalAlert(Base):
    """One durable operational notice to a member of the operation.

    Deliberately *not* an Outbox row. ADR-0045 gates messages to a Contact;
    these go to the operation's own people on a private channel, and applying
    consent or a service window to them would be meaningless. What they do
    share is durability: the row is created in the transaction that caused it,
    and delivery is a separate claimable step, which is what makes the
    escalation survive a restart.
    """

    __tablename__ = "internal_alerts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    #: NULL means every Organization Administrator.
    recipient_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: The at-most-once key. Derived from what the alert is about, never from a
    #: clock, so a retry or a restart produces the same key.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(14), nullable=False, default=InternalAlertStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Sent', 'Undeliverable', 'Failed')",
            name="ck_internal_alert_status",
        ),
        UniqueConstraint(
            "organization_id", "dedupe_key", name="uq_internal_alert_dedupe"
        ),
        Index("ix_internal_alerts_pending", "status", "created_at"),
        Index("ix_internal_alerts_recipient", "recipient_member_id", "created_at"),
        Index(
            "ix_internal_alerts_open",
            "organization_id",
            "created_at",
            postgresql_where=sql_text("acknowledged_at IS NULL"),
        ),
    )


class AppointmentReminder(Base):
    """One scheduled Contact-facing reminder for one appointment.

    Created deterministically when the visit is confirmed so the schedule can be
    inspected and asserted on. Dispatch is separately gated: the cadence is an
    unvalidated hypothesis (SAN-036) and every send still passes the Outbound
    Eligibility Gate, which denies free-form text outside the 24-hour window.
    """

    __tablename__ = "appointment_reminders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: Stamped whether the reminder was sent or deliberately withheld, so a
    #: blocked policy cannot make the worker retry the same reminder forever.
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: ``Sent``, or the stable reason it was not.
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('DayBefore', 'DayOf')", name="ck_reminder_kind"),
        UniqueConstraint("appointment_id", "kind", name="uq_reminder_appointment_kind"),
        Index("ix_reminders_due", "settled_at", "due_at"),
    )


# ==========================================================================
# Stage 4 — authoritative real-estate catalog
#
# Property is physical truth.  CatalogListing is one source publication and
# ListingOffer is one commercial operation.  Development and UnitModel do not
# imply that a physical Property exists.  ListingMedia is source/authority data
# owned by Product; Maia only receives approved projected URLs.
# ===========================================================================


class Development(Base):
    __tablename__ = "developments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    development_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    facts_review_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FactsReviewState.PENDING.value
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "facts_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_developments_facts_review",
        ),
        UniqueConstraint(
            "organization_id", "development_key", name="uq_developments_org_key"
        ),
        UniqueConstraint("organization_id", "id", name="uq_developments_org_id"),
    )


class UnitModel(Base):
    __tablename__ = "unit_models"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    development_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    facts_review_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FactsReviewState.PENDING.value
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "development_id"],
            ["developments.organization_id", "developments.id"],
            ondelete="CASCADE",
            name="fk_unit_models_development_org",
        ),
        CheckConstraint(
            "facts_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_unit_models_facts_review",
        ),
        UniqueConstraint(
            "development_id", "model_key", name="uq_unit_models_development_key"
        ),
        UniqueConstraint("organization_id", "id", name="uq_unit_models_org_id"),
    )


class CatalogListing(Base):
    __tablename__ = "catalog_listings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    listing_key: Mapped[str] = mapped_column(String(140), nullable=False)
    property_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    unit_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    public_location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    facts_review_state: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[str] = mapped_column(String(30), nullable=False)
    publication_state: Mapped[str] = mapped_column(String(20), nullable=False)
    authority: Mapped[str] = mapped_column(String(20), nullable=False)
    authority_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    freshness_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revalidate_by: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    automatic_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tier_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tier_override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    tier_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    readiness_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    readiness_override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    readiness_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    presentation_policy_version: Mapped[str] = mapped_column(String(60), nullable=False)
    gallery_path: Mapped[str] = mapped_column(String(240), nullable=False, unique=True)
    technical_sheet_path: Mapped[str] = mapped_column(
        String(240), nullable=False, unique=True
    )
    legacy_document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_document_versions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "property_uuid"],
            ["properties.organization_id", "properties.id"],
            ondelete="RESTRICT",
            name="fk_catalog_listings_property_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "unit_model_id"],
            ["unit_models.organization_id", "unit_models.id"],
            ondelete="RESTRICT",
            name="fk_catalog_listings_unit_model_org",
        ),
        CheckConstraint(
            "(property_uuid IS NOT NULL) <> (unit_model_id IS NOT NULL)",
            name="ck_catalog_listings_subject",
        ),
        CheckConstraint(
            "source_kind IN ('Organization', 'Collaborator')",
            name="ck_catalog_listings_source_kind",
        ),
        CheckConstraint(
            "facts_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_catalog_listings_facts_review",
        ),
        CheckConstraint(
            "availability IN ('Available', 'Reserved', 'Sold', 'Rented', "
            "'TemporarilyUnavailable', 'Unknown')",
            name="ck_catalog_listings_availability",
        ),
        CheckConstraint(
            "publication_state IN ('Draft', 'Published', 'Unpublished')",
            name="ck_catalog_listings_publication",
        ),
        CheckConstraint(
            "authority IN ('Authorized', 'Pending', 'Expired', 'Revoked')",
            name="ck_catalog_listings_authority",
        ),
        CheckConstraint(
            "automatic_tier IS NULL OR automatic_tier IN "
            "('Larevia', 'Premium', 'SuperPremium')",
            name="ck_catalog_listings_auto_tier",
        ),
        CheckConstraint(
            "tier_override IS NULL OR tier_override IN "
            "('Larevia', 'Premium', 'SuperPremium')",
            name="ck_catalog_listings_tier_override",
        ),
        CheckConstraint(
            "(tier_override IS NULL) = "
            "(tier_override_by IS NULL AND tier_override_at IS NULL)",
            name="ck_catalog_listings_tier_override_actor",
        ),
        CheckConstraint(
            "(readiness_override AND readiness_override_by IS NOT NULL "
            "AND readiness_override_at IS NOT NULL) OR "
            "(NOT readiness_override AND readiness_override_by IS NULL "
            "AND readiness_override_at IS NULL)",
            name="ck_catalog_listings_readiness_override_actor",
        ),
        UniqueConstraint(
            "organization_id", "listing_key", name="uq_catalog_listings_org_key"
        ),
        UniqueConstraint("organization_id", "id", name="uq_catalog_listings_org_id"),
        Index(
            "ix_catalog_listings_eligibility",
            "organization_id",
            "publication_state",
            "authority",
            "availability",
        ),
        Index("ix_catalog_listings_property", "property_uuid", "source_kind"),
    )


class ListingOffer(Base):
    __tablename__ = "listing_offers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_visibility: Mapped[str] = mapped_column(String(10), nullable=False)
    hidden_price_copy: Mapped[str | None] = mapped_column(String(120), nullable=True)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    terms_review_state: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[str] = mapped_column(String(30), nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legacy_document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_document_versions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "listing_id"],
            ["catalog_listings.organization_id", "catalog_listings.id"],
            ondelete="CASCADE",
            name="fk_listing_offers_listing_org",
        ),
        CheckConstraint(
            "operation IN ('Sale', 'Rental', 'Presale')",
            name="ck_listing_offers_operation",
        ),
        CheckConstraint("price_amount > 0", name="ck_listing_offers_price"),
        CheckConstraint(
            "price_currency IN ('MXN', 'USD')", name="ck_listing_offers_currency"
        ),
        CheckConstraint(
            "price_visibility IN ('Visible', 'Hidden')",
            name="ck_listing_offers_visibility",
        ),
        CheckConstraint(
            "(price_visibility = 'Hidden') = (hidden_price_copy IS NOT NULL)",
            name="ck_listing_offers_hidden_copy",
        ),
        CheckConstraint(
            "terms_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_listing_offers_terms_review",
        ),
        CheckConstraint(
            "availability IN ('Available', 'Reserved', 'Completed', "
            "'TemporarilyUnavailable', 'Withdrawn', 'Unknown')",
            name="ck_listing_offers_availability",
        ),
        UniqueConstraint("listing_id", "operation", name="uq_listing_offers_operation"),
        UniqueConstraint("organization_id", "id", name="uq_listing_offers_org_id"),
        Index("ix_listing_offers_listing_availability", "listing_id", "availability"),
    )


class ListingMedia(Base):
    __tablename__ = "listing_media"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[str] = mapped_column(String(20), nullable=False)
    authority_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_cover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    space_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    high_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cache_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    storage_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cache_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "listing_id"],
            ["catalog_listings.organization_id", "catalog_listings.id"],
            ondelete="CASCADE",
            name="fk_listing_media_listing_org",
        ),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_listing_media_type",
        ),
        CheckConstraint("byte_size > 0", name="ck_listing_media_size"),
        CheckConstraint("length(checksum) = 64", name="ck_listing_media_checksum"),
        CheckConstraint(
            "authority IN ('Authorized', 'Pending', 'Expired', 'Revoked')",
            name="ck_listing_media_authority",
        ),
        CheckConstraint("sort_order >= 0", name="ck_listing_media_order"),
        CheckConstraint(
            "(authority = 'Revoked') = "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)",
            name="ck_listing_media_revocation",
        ),
        Index(
            "uq_listing_media_cover",
            "listing_id",
            unique=True,
            postgresql_where=sql_text("is_cover IS TRUE AND revoked_at IS NULL"),
        ),
        Index(
            "uq_listing_media_order",
            "listing_id",
            "sort_order",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
        Index(
            "uq_listing_media_checksum",
            "listing_id",
            "checksum",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
        Index("ix_listing_media_authority", "listing_id", "authority", "sort_order"),
    )


class SavedCollection(Base):
    """One server-authoritative collection reached through an opaque cookie."""

    __tablename__ = "saved_collections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protected_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=True
    )
    # A device keeps its original cookie after WhatsApp protection. Following
    # this pointer lets that device reach the merged protected collection
    # without exposing a replacement token through the channel handoff.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_collections.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "protected_contact_id IS NULL OR expires_at IS NULL",
            name="ck_saved_collections_protected_no_expiry",
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id",
            name="ck_saved_collections_not_self_merged",
        ),
        Index(
            "uq_saved_collections_protected_contact",
            "organization_id",
            "protected_contact_id",
            unique=True,
            postgresql_where=sql_text(
                "protected_contact_id IS NOT NULL AND deleted_at IS NULL "
                "AND merged_into_id IS NULL"
            ),
        ),
        Index("ix_saved_collections_expiry", "expires_at"),
    )


class SavedCollectionItem(Base):
    __tablename__ = "saved_collection_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_collections.id", ondelete="CASCADE"), nullable=False
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_listings.id", ondelete="RESTRICT"), nullable=False
    )
    slug_snapshot: Mapped[str] = mapped_column(String(140), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    location_snapshot: Mapped[str | None] = mapped_column(String(300), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("collection_id", "listing_id", name="uq_saved_collection_item"),
        Index("ix_saved_collection_items_collection", "collection_id", "saved_at"),
    )


class SharedSelection(Base):
    """A revocable, immutable snapshot of selected Listing identifiers."""

    __tablename__ = "shared_selections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_collections.id", ondelete="CASCADE"), nullable=False
    )
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_shared_selections_expiry", "expires_at"),)


class WebsiteConversation(Base):
    """An anonymous website thread, intentionally separate from WhatsApp."""

    __tablename__ = "website_conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hermes_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=True
    )
    listing_context: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WebsiteConversationStatus.OPEN.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Open', 'HandoffPending', 'Verified', 'Closed')",
            name="ck_website_conversations_status",
        ),
        CheckConstraint(
            "(verified_contact_id IS NULL AND status IN ('Open', 'HandoffPending')) OR "
            "(verified_contact_id IS NOT NULL AND status IN ('Verified', 'Closed'))",
            name="ck_website_conversations_verified_contact",
        ),
        Index("ix_website_conversations_activity", "last_activity_at"),
    )


class WebsiteMessage(Base):
    __tablename__ = "website_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("website_conversations.id", ondelete="CASCADE"), nullable=False
    )
    command_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("role IN ('Customer', 'Maia', 'System')", name="ck_website_messages_role"),
        Index("ix_website_messages_thread", "conversation_id", "created_at"),
        Index(
            "ix_website_messages_expiry",
            "content_expires_at",
            postgresql_where=sql_text("content_expired_at IS NULL"),
        ),
    )


class ChannelHandoff(Base):
    """A short-lived, single-use reference crossing site and verified WhatsApp."""

    __tablename__ = "channel_handoffs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    website_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("website_conversations.id", ondelete="CASCADE"), nullable=True
    )
    saved_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_collections.id", ondelete="CASCADE"), nullable=True
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_listings.id", ondelete="RESTRICT"), nullable=True
    )
    expected_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('ContinueWhatsApp', 'Appointment', 'SavedCollectionProtection')",
            name="ck_channel_handoffs_purpose",
        ),
        CheckConstraint(
            "(consumed_at IS NULL) = (consumed_by_contact_id IS NULL)",
            name="ck_channel_handoffs_consumed",
        ),
        CheckConstraint(
            "website_conversation_id IS NOT NULL OR saved_collection_id IS NOT NULL "
            "OR listing_id IS NOT NULL",
            name="ck_channel_handoffs_context",
        ),
        Index("ix_channel_handoffs_expiry", "expires_at"),
    )


class PublicAnalyticsEvent(Base):
    """Allowlisted, non-PII public funnel evidence; never raw interaction data."""

    __tablename__ = "public_analytics_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_listings.id", ondelete="RESTRICT"), nullable=True
    )
    presentation_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    surface: Mapped[str] = mapped_column(String(40), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "name IN ('ListingImpression', 'GalleryOpen', 'ListingSaved', "
            "'MaiaStarted', 'HandoffCreated', 'AppointmentRequested')",
            name="ck_public_analytics_event_name",
        ),
        CheckConstraint(
            "presentation_tier IS NULL OR presentation_tier IN "
            "('Larevia', 'Premium', 'SuperPremium')",
            name="ck_public_analytics_tier",
        ),
        Index("ix_public_analytics_funnel", "organization_id", "occurred_at", "name"),
    )


class ExternalListingCandidate(Base):
    """A source record under review; deliberately not an authoritative Listing."""

    __tablename__ = "external_listing_candidates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_listing_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    municipality: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location_precision: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Unknown"
    )
    property_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    availability: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ListingAvailability.UNKNOWN.value
    )
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_agency: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExternalCandidateState.PENDING.value
    )
    authority_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    collaboration_authorized: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    commission_known: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    commission: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    commercial_review_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FactsReviewState.PENDING.value
    )
    mapping_issues: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    changed_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cache_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source_scope IN ('Organization', 'Collaborator')",
            name="ck_external_candidates_scope",
        ),
        CheckConstraint(
            "location_precision IN ('Exact', 'Approximate', 'Unknown')",
            name="ck_external_candidates_location_precision",
        ),
        CheckConstraint(
            "availability IN ('Available', 'Reserved', 'Sold', 'Rented', "
            "'TemporarilyUnavailable', 'Unknown')",
            name="ck_external_candidates_availability",
        ),
        CheckConstraint(
            "authority_state IN ('Authorized', 'Pending', 'Denied')",
            name="ck_external_candidates_authority",
        ),
        CheckConstraint(
            "commercial_review_state IN ('Pending', 'Approved', 'NeedsReview')",
            name="ck_external_candidates_commercial_review",
        ),
        CheckConstraint(
            "(withdrawn_at IS NULL AND deletion_due_at IS NULL) OR "
            "(withdrawn_at IS NOT NULL AND deletion_due_at IS NOT NULL)",
            name="ck_external_candidates_withdrawal_deadline",
        ),
        UniqueConstraint(
            "organization_id",
            "source",
            "source_listing_id",
            name="uq_external_candidates_source_identity",
        ),
        UniqueConstraint(
            "organization_id", "id", name="uq_external_candidates_org_id"
        ),
        Index(
            "ix_external_candidates_search",
            "organization_id",
            "source",
            "municipality",
            "authority_state",
            "availability",
        ),
        Index(
            "ix_external_candidates_cleanup",
            "deletion_due_at",
            postgresql_where=sql_text("cache_deleted_at IS NULL"),
        ),
    )


class ExternalOfferCandidate(Base):
    """A lossless source Offer mapping beneath one External Listing Candidate."""

    __tablename__ = "external_offer_candidates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    listing_candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    source_offer_key: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    price_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    availability: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OfferAvailability.UNKNOWN.value
    )
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "listing_candidate_id"],
            [
                "external_listing_candidates.organization_id",
                "external_listing_candidates.id",
            ],
            ondelete="CASCADE",
            name="fk_external_offers_candidate_org",
        ),
        CheckConstraint(
            "operation IS NULL OR operation IN ('Sale', 'Rental', 'Presale')",
            name="ck_external_offers_operation",
        ),
        CheckConstraint(
            "price_amount IS NULL OR price_amount > 0",
            name="ck_external_offers_price",
        ),
        CheckConstraint(
            "availability IN ('Available', 'Reserved', 'Completed', "
            "'TemporarilyUnavailable', 'Withdrawn', 'Unknown')",
            name="ck_external_offers_availability",
        ),
        UniqueConstraint(
            "listing_candidate_id",
            "source_offer_key",
            name="uq_external_offers_source_key",
        ),
        Index(
            "ix_external_offers_listing",
            "listing_candidate_id",
            "availability",
        ),
    )


class InventorySourceHealthRecord(Base):
    __tablename__ = "inventory_source_health"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InventorySourceStatus.NEVER_SYNCED.value
    )
    credential_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    mls_access_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    retention_permission_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_cursor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_limited_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Disabled', 'NeverSynced', 'Healthy', 'Partial', "
            "'RateLimited', 'Failed')",
            name="ck_inventory_source_health_status",
        ),
        CheckConstraint(
            "fetched_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0",
            name="ck_inventory_source_health_counts",
        ),
        UniqueConstraint(
            "organization_id", "source", name="uq_inventory_source_health"
        ),
    )


class ListingRevalidationRecord(Base):
    __tablename__ = "listing_revalidations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    listing_candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    intended_action: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    snapshot_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "listing_candidate_id"],
            [
                "external_listing_candidates.organization_id",
                "external_listing_candidates.id",
            ],
            ondelete="CASCADE",
            name="fk_listing_revalidations_candidate_org",
        ),
        CheckConstraint(
            "intended_action IN ('Recommend', 'Share', 'Appointment')",
            name="ck_listing_revalidations_action",
        ),
        CheckConstraint(
            "outcome IN ('Eligible', 'Pending', 'Denied')",
            name="ck_listing_revalidations_outcome",
        ),
        Index(
            "ix_listing_revalidations_candidate",
            "listing_candidate_id",
            "evaluated_at",
        ),
    )


# ==========================================================================
# Stage 7 — reviewed reactivation and bounded development campaigns
#
# The rows below are decisions and snapshots, not a second delivery system.
# A Candidate or Audience member can only gain an Outbox reference through
# OutboundMessaging.request, which keeps consent, suppression, reply and Meta
# template checks authoritative at both request and delivery time (ADR-0045).
# ==========================================================================


class ApprovedMessageTemplate(Base):
    """Last observed provider truth for one exact WABA template and language."""

    __tablename__ = "approved_message_templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    waba_id: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_template_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    template_name: Mapped[str] = mapped_column(String(120), nullable=False)
    language_code: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(20), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quality: Mapped[str | None] = mapped_column(String(30), nullable=True)
    component_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_api_version: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="MetaGraphAPI"
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('Marketing', 'Utility', 'Service')",
            name="ck_message_templates_category",
        ),
        CheckConstraint(
            "provider_status IN ('Approved', 'Pending', 'Rejected', 'Paused', "
            "'Disabled', 'Deleted')",
            name="ck_message_templates_status",
        ),
        UniqueConstraint(
            "organization_id",
            "template_name",
            "language_code",
            name="uq_message_templates_identity",
        ),
        Index(
            "ix_message_templates_approved",
            "organization_id",
            "provider_status",
            "category",
        ),
    )


class ReactivationCandidate(Base):
    """One explainable Listing match awaiting a human outreach decision."""

    __tablename__ = "reactivation_candidates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_need_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_needs.id", ondelete="CASCADE"),
        nullable=False,
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReactivationCandidateStatus.PENDING.value
    )
    match_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(60), nullable=False)
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    template_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Authorized', 'Rejected', 'Revoked', "
            "'Queued', 'Denied', 'Responded')",
            name="ck_reactivation_candidates_status",
        ),
        CheckConstraint(
            "match_kind IN ('Exact', 'Approximate')",
            name="ck_reactivation_candidates_match_kind",
        ),
        CheckConstraint(
            "(status = 'Pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(status <> 'Pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_reactivation_candidates_review",
        ),
        UniqueConstraint(
            "property_need_id",
            "listing_id",
            "rule_version",
            name="uq_reactivation_candidate_match",
        ),
        Index(
            "ix_reactivation_candidates_work",
            "organization_id",
            "status",
            "created_at",
        ),
    )


class DevelopmentCampaign(Base):
    """An explicit, versioned and pausable audience plan for one Development."""

    __tablename__ = "development_campaigns"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    development_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("developments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DevelopmentCampaignStatus.DRAFT.value
    )
    criteria_version: Mapped[str] = mapped_column(String(60), nullable=False)
    audience_criteria: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    exclusions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    template_name: Mapped[str] = mapped_column(String(120), nullable=False)
    template_language: Mapped[str] = mapped_column(String(20), nullable=False)
    content_preview: Mapped[str] = mapped_column(Text, nullable=False)
    quiet_hours_start: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    quiet_hours_end: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    timezone: Mapped[str] = mapped_column(
        String(60), nullable=False, default="America/Mexico_City"
    )
    frequency_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    frequency_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    max_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    authorized_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Draft', 'Active', 'Paused', 'Cancelled', 'Completed')",
            name="ck_development_campaigns_status",
        ),
        CheckConstraint(
            "quiet_hours_start BETWEEN 0 AND 23 AND quiet_hours_end BETWEEN 0 AND 23",
            name="ck_development_campaigns_quiet_hours",
        ),
        CheckConstraint(
            "frequency_cap > 0 AND frequency_window_days > 0 AND "
            "max_recipients > 0 AND max_recipients <= 500",
            name="ck_development_campaigns_limits",
        ),
        Index(
            "ix_development_campaigns_work",
            "organization_id",
            "status",
            "created_at",
        ),
    )


class CampaignAudienceMember(Base):
    """A PII-free-at-rest decision view for one explicit Property Need."""

    __tablename__ = "campaign_audience_members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("development_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_need_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("property_needs.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    audience_reference: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('Included', 'Excluded', 'Queued', 'Denied', 'Responded')",
            name="ck_campaign_audience_status",
        ),
        UniqueConstraint(
            "campaign_id", "property_need_id", name="uq_campaign_audience_need"
        ),
        UniqueConstraint(
            "campaign_id", "audience_reference", name="uq_campaign_audience_reference"
        ),
        Index("ix_campaign_audience_work", "campaign_id", "status", "resolved_at"),
    )


class MarketingTouch(Base):
    """One queued marketing contact, used for deduplication and frequency caps."""

    __tablename__ = "marketing_touches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("development_campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    reactivation_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reactivation_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbox_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(campaign_id IS NOT NULL) <> (reactivation_candidate_id IS NOT NULL)",
            name="ck_marketing_touches_source",
        ),
        UniqueConstraint("outbox_id", name="uq_marketing_touches_outbox"),
        Index(
            "ix_marketing_touches_frequency",
            "organization_id",
            "contact_id",
            "recorded_at",
        ),
    )
