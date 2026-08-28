"""The Outbound Eligibility Gate: may Product write to this person, right now?

Every message Product sends passes through :meth:`OutboundMessaging.request`.
Outbox stays what it always was — durable persistence and delivery — and this
module sits above it holding the one question Outbox must not answer.

The interface is deliberately small. A caller describes *what it wants to say
and why*, and receives :class:`Queued` or :class:`Denied`. It never assembles
consent, windows, templates, or suppression itself, and it cannot skip them:
staging an Outbox row is not exposed anywhere else.

Two properties matter more than the rule list:

* **Fail closed.** Anything the gate cannot positively justify is denied. A
  missing template, an absent consent record, an unknown recipient, and a
  closed customer-service window all produce a refusal, never a best effort.
* **Product decides, Hermes writes.** Hermes composes wording. It has no tool
  that reaches this module and cannot record consent. It cannot reach the
  Outbox at all: staging a row is not exposed anywhere else.

See ADR-0045.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    Conversation,
    InboxMessage,
    Lead,
    OutboundDecision,
    OutboundInitiation,
    OutboundOutcome,
    OutboxMessage,
    SuppressionRecord,
)
from realestate.domain.outbox import OutboxService
from realestate.domain.audit import record_audit
from realestate.domain.text import fold_phrase

# Meta only allows free-form text within 24 hours of the Contact's last message.
# Outside it, an approved template is the only lawful way to open a
# conversation. This is a platform constraint, so it is a product invariant.
SERVICE_WINDOW = timedelta(hours=24)

logger = logging.getLogger(__name__)


class Purpose(str, enum.Enum):
    """Why an outbound message exists.

    Kept separate from ``OutboxKind`` on purpose: kind describes the row that
    will be delivered, purpose describes the business reason the gate is being
    asked to authorise. They happen to share their names today.
    """

    AGENT_REPLY = "AgentReply"
    PROCESSING_FAILURE = "ProcessingFailureNotice"
    APPOINTMENT_CONFIRMATION = "AppointmentConfirmation"
    APPOINTMENT_RESOLUTION = "AppointmentResolution"
    APPOINTMENT_CANCELLATION = "AppointmentCancellation"
    APPOINTMENT_NEEDS_REVIEW = "AppointmentNeedsReview"
    LEAD_FOLLOW_UP = "LeadFollowUp"


# Which WhatsApp consent category each purpose consumes. Answering somebody who
# just wrote is service; telling them what happened to the appointment they
# asked for is utility; going out to revive a silent Contact is marketing, and
# marketing is the only one that needs a positive consent record.
PURPOSE_CATEGORY: dict[Purpose, ConsentCategory] = {
    Purpose.AGENT_REPLY: ConsentCategory.SERVICE,
    Purpose.PROCESSING_FAILURE: ConsentCategory.SERVICE,
    Purpose.APPOINTMENT_CONFIRMATION: ConsentCategory.UTILITY,
    Purpose.APPOINTMENT_RESOLUTION: ConsentCategory.UTILITY,
    Purpose.APPOINTMENT_CANCELLATION: ConsentCategory.UTILITY,
    Purpose.APPOINTMENT_NEEDS_REVIEW: ConsentCategory.UTILITY,
    Purpose.LEAD_FOLLOW_UP: ConsentCategory.MARKETING,
}

# Purposes that a Contact's own reply must interrupt. A generic follow-up to
# somebody who has already answered is the exact failure ADR-0021 forbids.
STOPS_ON_REPLY: frozenset[Purpose] = frozenset({Purpose.LEAD_FOLLOW_UP})

# Templates Meta has approved for this WhatsApp Business Account, by id.
#
# Empty, and not a placeholder. Nothing in Product may add to it: a template is
# approved by Meta against a named WABA, and inventing an entry here would let
# the gate authorise a send that the platform will reject. Until real templates
# exist, every send outside the service window is denied — which is the honest
# outcome, because such a send would fail anyway.
@dataclass(frozen=True)
class ApprovedTemplate:
    """Provider-approved delivery metadata for one exact Meta template."""

    category: ConsentCategory
    language_code: str


APPROVED_TEMPLATES: dict[str, ApprovedTemplate] = {}

# ADR-0021 requires Opportunity/Next Action state, appointment/rejection
# awareness and a Dormant transition before the cadence can become live. Those
# commercial states do not exist yet, so consent plus a Meta template must not
# accidentally activate the sequence.
FOLLOW_UP_POLICY_ACTIVATED = False


class DenialReason(str, enum.Enum):
    """Why the gate refused. Stable codes: they are recorded and reported on."""

    UNKNOWN_RECIPIENT = "UnknownRecipient"
    MISSING_REACTIVE_TRIGGER = "MissingReactiveTrigger"
    UNTRUSTED_TRIGGER = "UntrustedTrigger"
    SUPPRESSED = "Suppressed"
    CONTACT_REPLIED = "ContactReplied"
    MARKETING_CONSENT_MISSING = "MarketingConsentMissing"
    SERVICE_WINDOW_CLOSED = "ServiceWindowClosed"
    TEMPLATE_NOT_APPROVED = "TemplateNotApproved"
    TEMPLATE_METADATA_INCOMPLETE = "TemplateMetadataIncomplete"
    TEMPLATE_CATEGORY_MISMATCH = "TemplateCategoryMismatch"
    FOLLOW_UP_POLICY_INACTIVE = "FollowUpPolicyInactive"
    ELIGIBILITY_EVIDENCE_MISSING = "EligibilityEvidenceMissing"


@dataclass(frozen=True)
class OutboundIntent:
    """One request to say something to one Contact.

    ``initiation`` is the caller's declaration and ``trigger_inbox_ids`` is the
    evidence behind it. The declaration is recorded, not believed: the gate
    computes the service window from persisted inbound messages and rejects
    trigger ids that do not belong to the Conversation.

    Declaring ``Reactive`` does skip the outreach rules — suppression, consent,
    stop-on-reply — because answering somebody who just wrote is not outreach.
    What keeps that sound is that the window check applies to *every* intent
    regardless of declaration: a Contact who has not written in 24 hours cannot
    be written to at all without an approved template.

    Deliberately small. The recipient, the Outbox kind, the consent category and
    the request time are all derived here rather than asked of six call sites
    that would otherwise each get a chance to disagree.
    """

    conversation: Conversation
    body: str
    purpose: Purpose
    initiation: OutboundInitiation
    idempotency_key: str
    requested_at: datetime = field(default_factory=lambda: _now())
    trigger_inbox_ids: tuple[uuid.UUID, ...] = ()
    inbox_group_id: uuid.UUID | None = None
    template_id: str | None = None
    template_category: ConsentCategory | None = None

    @property
    def category(self) -> ConsentCategory:
        return PURPOSE_CATEGORY[self.purpose]

    @property
    def kind(self) -> str:
        """The Outbox kind. Purpose and kind name the same set of messages."""
        return self.purpose.value


@dataclass(frozen=True)
class Refusal:
    """A rule's verdict, before it becomes a recorded decision."""

    reason: DenialReason
    detail: str


@dataclass(frozen=True)
class Queued:
    """The message was authorised and staged in the Outbox."""

    decision_id: uuid.UUID
    outbox_id: uuid.UUID
    created: bool


@dataclass(frozen=True)
class Denied:
    """The message was refused. Nothing was staged."""

    decision_id: uuid.UUID
    reason: DenialReason
    detail: str


@dataclass(frozen=True)
class TextDelivery:
    """A revalidated free-form delivery inside the live service window."""

    to_wa_id: str
    body: str


@dataclass(frozen=True)
class TemplateDelivery:
    """A revalidated Meta template delivery outside or inside the window."""

    to_wa_id: str
    template_id: str
    language_code: str


@dataclass(frozen=True)
class DeliveryDenied:
    """A queued row that failed the final, delivery-time eligibility check."""

    reason: DenialReason
    detail: str


def _now() -> datetime:
    return datetime.now(tz=UTC)


class OutboundMessaging:
    """The only way an outbound message comes into existence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request(self, intent: OutboundIntent) -> Queued | Denied:
        """Authorise and stage one outbound message.

        Never commits. The decision, the Outbox row, and whatever state the
        caller keeps about the attempt all belong to one transaction, so a
        crash cannot leave a message queued that no decision authorised, or a
        follow-up recorded as sent that was never staged.
        """
        lead = await self._lead(intent.conversation)
        if lead is None:  # pragma: no cover - see below
            # Unreachable through the schema: ``Conversation.lead_id`` is NOT
            # NULL with a foreign key, so a live Conversation always has a Lead.
            # It stays because it is reachable through a race — another
            # transaction deleting the Lead cascades the Conversation away while
            # a caller still holds the stale object — and the only safe answer
            # there is to refuse. Recording the refusal will then fail on the
            # same foreign key and roll the caller back, which is still the
            # outcome that matters: no message goes out.
            return await self._deny(
                intent,
                lead=None,
                reason=DenialReason.UNKNOWN_RECIPIENT,
                detail="The Conversation has no Lead to write to.",
                window=None,
            )

        if (
            intent.initiation is OutboundInitiation.REACTIVE
            and not intent.trigger_inbox_ids
        ):
            return await self._deny(
                intent,
                lead=lead,
                reason=DenialReason.MISSING_REACTIVE_TRIGGER,
                detail="A reactive message must name the inbound messages it answers.",
                window=None,
            )

        if not await self._triggers_belong(intent):
            return await self._deny(
                intent,
                lead=lead,
                reason=DenialReason.UNTRUSTED_TRIGGER,
                detail="Trigger messages do not belong to this Conversation.",
                window=None,
            )

        # The outreach rules first: they are the ones a Contact can revoke, and
        # a refusal here should say so rather than blaming a template. The
        # window is not needed to reach these verdicts, so it is not paid for.
        if intent.initiation is OutboundInitiation.BUSINESS_INITIATED:
            refusal = await self._business_initiated_refusal(intent, lead)
            if refusal is not None:
                return await self._deny(
                    intent,
                    lead=lead,
                    reason=refusal.reason,
                    detail=refusal.detail,
                    window=None,
                )

        # A supplied template must be valid whether or not the window is open;
        # a closed window must have one. Both directions fail closed.
        window = await self._service_window_expiry(lead)
        if (intent.template_id is None) is not (intent.template_category is None):
            refusal = Refusal(
                DenialReason.TEMPLATE_METADATA_INCOMPLETE,
                "Template identifier and category must be supplied together.",
            )
        elif intent.template_id is not None:
            refusal = self._template_refusal(intent)
        elif window is None or intent.requested_at >= window:
            refusal = Refusal(
                DenialReason.SERVICE_WINDOW_CLOSED,
                "Outside the 24-hour customer-service window and no "
                "approved template was supplied.",
            )
        else:
            refusal = None
        if refusal is not None:
            return await self._deny(
                intent,
                lead=lead,
                reason=refusal.reason,
                detail=refusal.detail,
                window=window,
            )

        staged = await OutboxService(self._session).stage(
            conversation=intent.conversation,
            # The recipient is the Lead the gate just authorised, not an address
            # the caller supplies: those two must not be able to disagree.
            to_wa_id=lead.wa_id,
            body=intent.body,
            kind=intent.kind,
            idempotency_key=intent.idempotency_key,
            covered_inbox_ids=list(intent.trigger_inbox_ids),
            inbox_group_id=intent.inbox_group_id,
        )
        if not staged.created:
            # This intent was already authorised. Re-deciding it would claim a
            # second authorisation for one message; the caller wants the
            # original, which is also what the partial unique index enforces.
            previous = await self._session.scalar(
                select(OutboundDecision)
                .where(OutboundDecision.idempotency_key == intent.idempotency_key)
                .where(OutboundDecision.outcome == OutboundOutcome.QUEUED.value)
                .limit(1)
            )
            if previous is not None:
                return Queued(
                    decision_id=previous.id,
                    outbox_id=staged.outbox_id,
                    created=False,
                )

        decision = await self._record(
            intent,
            lead=lead,
            outcome=OutboundOutcome.QUEUED,
            window=window,
            outbox_id=staged.outbox_id,
        )
        return Queued(
            decision_id=decision.id,
            outbox_id=staged.outbox_id,
            created=staged.created,
        )

    async def prepare_delivery(
        self,
        row: OutboxMessage,
        *,
        now: datetime | None = None,
    ) -> TextDelivery | TemplateDelivery | DeliveryDenied:
        """Revalidate one claimed row immediately before contacting Meta.

        Request-time eligibility is necessary but not sufficient: a Contact can
        reply or opt out while a row waits, and a free-form service window can
        expire during retries. This method locks the Lead through the provider
        call; Inbox acceptance uses the same lock, giving those races a causal
        order instead of a read/check/send gap.

        A denial is committed here to release the lock and permanently
        quarantine the row. An allowed result leaves the transaction open; the
        worker's normal delivery-result commit closes it after Meta answers.
        """
        decision = await self._session.scalar(
            select(OutboundDecision)
            .where(OutboundDecision.outbox_id == row.id)
            .where(OutboundDecision.outcome == OutboundOutcome.QUEUED.value)
            .limit(1)
        )
        if decision is None:
            return await self._block_delivery(
                row,
                DenialReason.ELIGIBILITY_EVIDENCE_MISSING,
                "The queued row has no recorded Queued eligibility decision.",
            )
        if decision.conversation_id != row.conversation_id:
            return await self._block_delivery(
                row,
                DenialReason.ELIGIBILITY_EVIDENCE_MISSING,
                "The queued decision belongs to another Conversation.",
            )

        conversation = await self._session.get(Conversation, row.conversation_id)
        if conversation is None:
            return await self._block_delivery(
                row,
                DenialReason.UNKNOWN_RECIPIENT,
                "The queued row's Conversation no longer exists.",
            )
        lead = await self._lead(conversation)
        if lead is None or lead.wa_id != row.to_wa_id:
            return await self._block_delivery(
                row,
                DenialReason.ELIGIBILITY_EVIDENCE_MISSING,
                "The queued recipient no longer matches Product truth.",
            )

        try:
            purpose = Purpose(decision.purpose)
            initiation = OutboundInitiation(decision.initiation)
            triggers = tuple(uuid.UUID(value) for value in decision.trigger_inbox_ids)
            category = (
                ConsentCategory(decision.template_category)
                if decision.template_category is not None
                else None
            )
        except (TypeError, ValueError):
            return await self._block_delivery(
                row,
                DenialReason.ELIGIBILITY_EVIDENCE_MISSING,
                "The queued decision contains unreadable eligibility evidence.",
            )
        intent = OutboundIntent(
            conversation=conversation,
            body=row.body,
            purpose=purpose,
            initiation=initiation,
            idempotency_key=decision.idempotency_key,
            requested_at=decision.requested_at,
            trigger_inbox_ids=triggers,
            inbox_group_id=row.inbox_group_id,
            template_id=decision.template_id,
            template_category=category,
        )
        if intent.kind != row.kind:
            return await self._block_delivery(
                row,
                DenialReason.ELIGIBILITY_EVIDENCE_MISSING,
                "The queued purpose and Outbox kind do not match.",
            )
        if initiation is OutboundInitiation.REACTIVE and not triggers:
            return await self._block_delivery(
                row,
                DenialReason.MISSING_REACTIVE_TRIGGER,
                "The queued reactive message has no inbound trigger evidence.",
            )
        if not await self._triggers_belong(intent):
            return await self._block_delivery(
                row,
                DenialReason.UNTRUSTED_TRIGGER,
                "The queued trigger messages do not belong to this Conversation.",
            )
        if initiation is OutboundInitiation.BUSINESS_INITIATED:
            refusal = await self._business_initiated_refusal(intent, lead)
            if refusal is not None:
                return await self._block_delivery(row, refusal.reason, refusal.detail)

        if (intent.template_id is None) is not (intent.template_category is None):
            return await self._block_delivery(
                row,
                DenialReason.TEMPLATE_METADATA_INCOMPLETE,
                "The queued template identifier and category are incomplete.",
            )
        if intent.template_id is not None:
            refusal = self._template_refusal(intent)
            if refusal is not None:
                return await self._block_delivery(row, refusal.reason, refusal.detail)
            approved = APPROVED_TEMPLATES[intent.template_id]
            return TemplateDelivery(
                to_wa_id=row.to_wa_id,
                template_id=intent.template_id,
                language_code=approved.language_code,
            )

        expiry = await self._service_window_expiry(lead)
        moment = now or _now()
        if expiry is None or moment >= expiry:
            return await self._block_delivery(
                row,
                DenialReason.SERVICE_WINDOW_CLOSED,
                "The free-form service window closed before delivery.",
            )
        return TextDelivery(to_wa_id=row.to_wa_id, body=row.body)

    # -- The rules --------------------------------------------------------

    async def _business_initiated_refusal(
        self, intent: OutboundIntent, lead: Lead
    ) -> Refusal | None:
        """What stops the operation from reaching out, in order of severity."""
        if await self._suppressed(lead):
            return Refusal(
                DenialReason.SUPPRESSED,
                "The Contact asked not to be contacted.",
            )

        if intent.purpose in STOPS_ON_REPLY and await self._contact_replied(intent):
            return Refusal(
                DenialReason.CONTACT_REPLIED,
                "The Contact has replied and is awaiting an answer.",
            )

        if (
            intent.purpose is Purpose.LEAD_FOLLOW_UP
            and not FOLLOW_UP_POLICY_ACTIVATED
        ):
            return Refusal(
                DenialReason.FOLLOW_UP_POLICY_INACTIVE,
                "The state-driven follow-up policy is not activated.",
            )

        if intent.category is ConsentCategory.MARKETING and not await self._granted(
            lead, ConsentCategory.MARKETING
        ):
            return Refusal(
                DenialReason.MARKETING_CONSENT_MISSING,
                "No current marketing consent is recorded for this Contact.",
            )

        return None

    def _template_refusal(self, intent: OutboundIntent) -> Refusal | None:
        """Whether the supplied template may carry this message."""
        approved = APPROVED_TEMPLATES.get(intent.template_id or "")
        if approved is None:
            return Refusal(
                DenialReason.TEMPLATE_NOT_APPROVED,
                f"Template {intent.template_id!r} is not an approved template.",
            )
        if intent.template_category is not intent.category:
            supplied = (
                intent.template_category.value
                if intent.template_category is not None
                else "None"
            )
            return Refusal(
                DenialReason.TEMPLATE_CATEGORY_MISMATCH,
                f"Template {intent.template_id!r} was supplied as {supplied}, "
                f"not {intent.category.value}.",
            )
        if approved.category is not intent.template_category:
            return Refusal(
                DenialReason.TEMPLATE_CATEGORY_MISMATCH,
                f"Template {intent.template_id!r} is approved for "
                f"{approved.category.value}, not {intent.template_category.value}.",
            )
        return None

    async def _lead(self, conversation: Conversation) -> Lead | None:
        lead: Lead | None = await self._session.scalar(
            select(Lead).where(Lead.id == conversation.lead_id).with_for_update()
        )
        return lead

    async def _triggers_belong(self, intent: OutboundIntent) -> bool:
        if not intent.trigger_inbox_ids:
            return True
        found = await self._session.scalar(
            select(func.count(InboxMessage.id))
            .where(InboxMessage.id.in_(intent.trigger_inbox_ids))
            .where(InboxMessage.conversation_id == intent.conversation.id)
        )
        return found == len(set(intent.trigger_inbox_ids))

    async def _service_window_expiry(self, lead: Lead) -> datetime | None:
        """When Meta's free-form window closes, from the Contact's own messages.

        Computed across the Lead's Conversations rather than one of them: the
        window belongs to the pair of phone numbers, not to an engagement cycle.
        """
        latest = await self._session.scalar(
            select(InboxMessage.sent_at)
            .join(Conversation, Conversation.id == InboxMessage.conversation_id)
            .where(Conversation.lead_id == lead.id)
            .order_by(InboxMessage.sent_at.desc())
            .limit(1)
        )
        if latest is None:
            return None
        return latest + SERVICE_WINDOW

    async def _suppressed(self, lead: Lead) -> bool:
        return await _active_suppression(self._session, lead.id) is not None

    async def _granted(self, lead: Lead, category: ConsentCategory) -> bool:
        """Whether the most recent statement for this category is a grant."""
        latest = await self._session.scalar(
            select(ConsentRecord.state)
            .where(ConsentRecord.lead_id == lead.id)
            .where(ConsentRecord.category == category.value)
            .order_by(ConsentRecord.recorded_at.desc(), ConsentRecord.id.desc())
            .limit(1)
        )
        return latest == ConsentState.GRANTED.value

    async def _contact_replied(self, intent: OutboundIntent) -> bool:
        """Has the Contact written since Product last wrote to them?

        This is what "any reply stops the sequence" means operationally. It also
        covers the case where Product never answered at all: then the Contact is
        owed a reply, and a generic follow-up is the wrong message entirely.
        """
        # ``persisted_at``, not ``sent_at``: this is compared against an Outbox
        # ``created_at``, and both are written by Product's own clock. Meta's
        # send timestamp belongs to the service window, which is Meta's rule.
        last_inbound = await self._session.scalar(
            select(InboxMessage.persisted_at)
            .where(InboxMessage.conversation_id == intent.conversation.id)
            .order_by(InboxMessage.persisted_at.desc())
            .limit(1)
        )
        if last_inbound is None:
            return False
        last_outbound = await self._session.scalar(
            select(OutboxMessage.created_at)
            .where(OutboxMessage.conversation_id == intent.conversation.id)
            .order_by(OutboxMessage.created_at.desc())
            .limit(1)
        )
        return last_outbound is None or last_inbound > last_outbound

    async def _record(
        self,
        intent: OutboundIntent,
        *,
        lead: Lead | None,
        outcome: OutboundOutcome,
        window: datetime | None,
        outbox_id: uuid.UUID | None = None,
        reason: DenialReason | None = None,
        detail: str | None = None,
    ) -> OutboundDecision:
        """Append the one row that proves the gate ran.

        Both outcomes go through here so a column added for one can never be
        missing from the other — asymmetric history is exactly what this table
        exists to prevent.
        """
        decision = OutboundDecision(
            conversation_id=intent.conversation.id,
            lead_id=lead.id if lead else None,
            idempotency_key=intent.idempotency_key,
            initiation=intent.initiation.value,
            purpose=intent.purpose.value,
            outcome=outcome.value,
            reason=reason.value if reason else None,
            detail=detail,
            trigger_inbox_ids=[str(i) for i in intent.trigger_inbox_ids],
            template_id=intent.template_id,
            template_category=(
                intent.template_category.value
                if intent.template_category is not None
                else None
            ),
            service_window_expires_at=window,
            outbox_id=outbox_id,
            requested_at=intent.requested_at,
            decided_at=_now(),
        )
        self._session.add(decision)
        await self._session.flush()
        return decision

    async def _deny(
        self,
        intent: OutboundIntent,
        *,
        lead: Lead | None,
        reason: DenialReason,
        detail: str,
        window: datetime | None,
    ) -> Denied:
        """Refuse, record why, and say so once.

        The log line lives here rather than at each call site: the gate already
        knows everything worth reporting, and callers that forget to log a
        refusal would otherwise make it invisible.
        """
        decision = await self._record(
            intent,
            lead=lead,
            outcome=OutboundOutcome.DENIED,
            window=window,
            reason=reason,
            detail=detail,
        )
        logger.info(
            "Withheld a %s message to conversation %s: %s (%s)",
            intent.purpose.value,
            intent.conversation.id,
            reason.value,
            detail,
        )
        return Denied(decision_id=decision.id, reason=reason, detail=detail)

    async def _block_delivery(
        self,
        row: OutboxMessage,
        reason: DenialReason,
        detail: str,
    ) -> DeliveryDenied:
        """Quarantine a claimed row and append auditable delivery evidence."""
        row.status = "Failed"
        row.last_error = f"Outbound eligibility withheld delivery: {reason.value}."
        row.next_attempt_at = None
        await record_audit(
            self._session,
            actor_type="Product",
            actor_id="OutboundEligibilityGate",
            action="WithholdOutboundAtDelivery",
            subject_type="OutboxMessage",
            subject_id=str(row.id),
            details={"reason": reason.value, "detail": detail},
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "Withheld outbox %s at delivery: %s (%s)",
            row.id,
            reason.value,
            detail,
        )
        return DeliveryDenied(reason=reason, detail=detail)


# -- Explicit opt-out ------------------------------------------------------

# A Contact asking to be left alone must be honoured whether or not anybody is
# watching, so the check is deterministic Product policy rather than model
# judgement. It is intentionally literal: the whole message must be one of
# these, which keeps "no me contactes por teléfono, mejor por aquí" out of it.
# Broadening this is a product decision, not a tuning exercise.
OPT_OUT_PHRASES: frozenset[str] = frozenset(
    {
        "baja",
        "darme de baja",
        "dar de baja",
        "stop",
        "unsubscribe",
        "no me contacten",
        "no me contactes",
        "no me escriban",
        "no me escribas",
        "ya no me contacten",
        "ya no me contactes",
        "ya no me escriban",
        "ya no me escribas",
        "dejen de escribirme",
        "deja de escribirme",
        "dejen de contactarme",
        "no quiero mas mensajes",
        "no quiero recibir mas mensajes",
        "no me manden mas mensajes",
        "eliminar mis datos",
    }
)

# The longest phrase above, with room to spare. The match is whole-message by
# design, so anything longer cannot be one and is not worth folding — and this
# runs on the webhook path, which must answer Meta promptly.
_LONGEST_OPT_OUT = max(len(phrase) for phrase in OPT_OUT_PHRASES) * 2


def detect_opt_out(text: str | None) -> str | None:
    """The matched opt-out phrase, or ``None``. Whole-message match only."""
    if not text or len(text) > _LONGEST_OPT_OUT:
        return None
    folded = fold_phrase(text)
    return folded if folded in OPT_OUT_PHRASES else None


async def _active_suppression(
    session: AsyncSession, lead_id: uuid.UUID
) -> uuid.UUID | None:
    """The Lead's live suppression, if any.

    One definition, used by the rule that reads it and the path that writes it,
    so they cannot drift apart from each other or from the partial unique index
    ``uq_suppression_active`` that enforces at most one.
    """
    found: uuid.UUID | None = await session.scalar(
        select(SuppressionRecord.id)
        .where(SuppressionRecord.lead_id == lead_id)
        .where(SuppressionRecord.revoked_at.is_(None))
        .limit(1)
    )
    return found


async def record_explicit_opt_out(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    phrase: str,
    source_inbox_id: uuid.UUID | None,
) -> bool:
    """Suppress business-initiated contact because the Contact asked.

    Never commits: the caller folds this into the transaction that accepted the
    message, so a Contact cannot be recorded as having opted out of a message
    that was not itself durably stored. Returns ``False`` when an active
    suppression already exists, which makes a duplicate webhook delivery a
    no-op.

    Reactive replies are deliberately still permitted. Suppression stops the
    operation from reaching out; it does not gag Product while the Contact is
    actively writing, including the acknowledgement of the opt-out itself.
    """
    if await _active_suppression(session, lead_id) is not None:
        return False

    session.add(
        SuppressionRecord(
            lead_id=lead_id,
            scope="BusinessInitiated",
            reason="ExplicitOptOut",
            evidence=phrase,
            source_inbox_id=source_inbox_id,
        )
    )
    # The same act is also a consent fact. Recording it here is what gives the
    # marketing category a real, dated Revoked state instead of mere absence.
    session.add(
        ConsentRecord(
            lead_id=lead_id,
            category=ConsentCategory.MARKETING.value,
            state=ConsentState.REVOKED.value,
            source="InboundOptOut",
            evidence=phrase,
        )
    )
    await session.flush()
    return True
