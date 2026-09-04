"""Larevia's commercial system of record (ADR-0022, ADR-0023).

One modular product, not a set of services. Each module below is deep: a small
interface over the transactions, invariants, idempotency and audit that the
capability actually needs. Routers, workers and templates call these interfaces
and hold none of those rules themselves.

The seams, and what each one is the only way to do:

* :class:`~realestate.domain.commercial.identity.CommercialIdentity` — turn a
  channel identity into a Contact;
* :class:`~realestate.domain.commercial.needs.PropertyNeeds` — record what the
  Contact wants, and how confirmed it is;
* :class:`~realestate.domain.commercial.opportunities.OpportunityManagement` —
  open an Opportunity and change its stage;
* :class:`~realestate.domain.commercial.assignment.Assignment` — decide who is
  responsible, or make the absence visible;
* :class:`~realestate.domain.commercial.next_actions.NextActions` — owe and
  discharge the next action;
* :class:`~realestate.domain.commercial.views.CommercialInbox` — everything an
  operator surface is allowed to read;
* :class:`~realestate.domain.commercial.intake.CommercialIntake` — the crossing
  from the customer-channel Inbox into commercial work;
* :class:`~realestate.domain.commercial.retention.ConversationRetention` and
  :class:`~realestate.domain.commercial.maintenance.CommercialMaintenance` —
  the rules that are about time rather than about a decision;
* :class:`~realestate.domain.commercial.organization.OrganizationDirectory` —
  the Organization and who belongs to it.
"""

from realestate.domain.commercial.actors import (
    Actor,
    Authority,
    CommercialError,
    InvalidTransition,
    MissingEvidence,
    NotAuthorized,
    NotFound,
    QualificationIncomplete,
    UnknownMember,
)
from realestate.domain.commercial.assignment import Assignment, AssignmentOutcome
from realestate.domain.commercial.identity import ChannelIdentity, CommercialIdentity
from realestate.domain.commercial.intake import CommercialIntake
from realestate.domain.commercial.maintenance import CommercialMaintenance
from realestate.domain.commercial.needs import CriterionStatement, PropertyNeeds
from realestate.domain.commercial.next_actions import (
    CompleteNextAction,
    NextActions,
    ScheduleNextAction,
)
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    OpenOpportunity,
    OpportunityManagement,
    OriginFacts,
    QualificationAction,
    RecordDormant,
    RecordLost,
    RecordWon,
)
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)
from realestate.domain.commercial.retention import ConversationRetention
from realestate.domain.commercial.transactions import Transactions
from realestate.domain.commercial.views import CommercialInbox, InboxFilters

__all__ = [
    "Actor",
    "AdvanceStage",
    "Assignment",
    "AssignmentOutcome",
    "Authority",
    "ChannelIdentity",
    "CommercialError",
    "CommercialIdentity",
    "CommercialInbox",
    "CommercialIntake",
    "CommercialMaintenance",
    "CompleteNextAction",
    "ConversationRetention",
    "CriterionStatement",
    "DirectoryPlan",
    "InboxFilters",
    "InvalidTransition",
    "MissingEvidence",
    "NextActions",
    "NotAuthorized",
    "NotFound",
    "OpenOpportunity",
    "OpportunityManagement",
    "OrganizationDirectory",
    "OriginFacts",
    "PropertyNeeds",
    "QualificationIncomplete",
    "QualificationAction",
    "RecordDormant",
    "RecordLost",
    "RecordWon",
    "ScheduleNextAction",
    "Transactions",
    "UnknownMember",
]
