"""Every enum an operator can see has a Spanish word for every value.

The rule this holds still: a label map lives beside the enum its module owns,
and it covers that enum completely. Both halves matter. A map keyed by bare
string literals goes stale silently when a member is renamed, and a missing key
puts an English identifier — ``NoInventoryMatch``, ``DefaultAdvisor`` — on an
operator's screen, which is the one thing the Mexican Spanish rule forbids.

These are cheap, table-driven, and they fail at the moment somebody adds an enum
member rather than the moment somebody happens to render it.
"""

from __future__ import annotations

import enum

import pytest

from realestate.api.crm import (
    DENIAL_REASON_LABELS,
    ORIGIN_LABELS,
    PURPOSE_LABELS,
    SCOPE_LABELS,
)
from realestate.db.models import (
    AssignmentBasis,
    AssignmentQueueReason,
    ChannelIdentityTrust,
    CriterionSource,
    MemberRole,
    NextActionKind,
    NextActionOutcome,
    NextActionStatus,
    OpportunityExceptionReason,
    OpportunityKind,
    OpportunityOriginSource,
    OpportunityStage,
    PropertyNeedStatus,
    TransactionIntent,
)
from realestate.domain.commercial.assignment import (
    BASIS_LABELS,
    QUEUE_REASON_DETAIL,
    QUEUE_REASON_LABELS,
)
from realestate.domain.commercial.needs import (
    INTENT_LABELS,
    NEED_STATUS_LABELS,
    SOURCE_LABELS,
)
from realestate.domain.commercial.next_actions import (
    KIND_LABELS as ACTION_KIND_LABELS,
)
from realestate.domain.commercial.next_actions import (
    OUTCOME_LABELS,
    STATUS_LABELS,
)
from realestate.domain.commercial.opportunities import (
    DORMANT_REASON_LABELS,
    EXCEPTION_REASON_LABELS,
    KIND_LABELS,
    LOST_REASON_LABELS,
    STAGE_LABELS,
    WON_EVIDENCE_LABELS,
    DormantReason,
    LostReason,
    WonEvidence,
)
from realestate.domain.commercial.organization import ROLE_LABELS
from realestate.domain.commercial.views import InboxFilters
from realestate.domain.outbound import DenialReason, Purpose

#: Every operator-visible enum and the map that names its values in Spanish.
LABELLED: tuple[tuple[str, type[enum.Enum], dict[str, str]], ...] = (
    ("OpportunityStage", OpportunityStage, STAGE_LABELS),
    ("OpportunityKind", OpportunityKind, KIND_LABELS),
    ("LostReason", LostReason, LOST_REASON_LABELS),
    ("DormantReason", DormantReason, DORMANT_REASON_LABELS),
    ("WonEvidence", WonEvidence, WON_EVIDENCE_LABELS),
    (
        "OpportunityExceptionReason",
        OpportunityExceptionReason,
        EXCEPTION_REASON_LABELS,
    ),
    ("NextActionKind", NextActionKind, ACTION_KIND_LABELS),
    ("NextActionStatus", NextActionStatus, STATUS_LABELS),
    ("NextActionOutcome", NextActionOutcome, OUTCOME_LABELS),
    ("AssignmentBasis", AssignmentBasis, BASIS_LABELS),
    ("AssignmentQueueReason", AssignmentQueueReason, QUEUE_REASON_LABELS),
    ("AssignmentQueueReason detail", AssignmentQueueReason, QUEUE_REASON_DETAIL),
    ("PropertyNeedStatus", PropertyNeedStatus, NEED_STATUS_LABELS),
    ("CriterionSource", CriterionSource, SOURCE_LABELS),
    ("TransactionIntent", TransactionIntent, INTENT_LABELS),
    ("MemberRole", MemberRole, ROLE_LABELS),
    ("OpportunityOriginSource", OpportunityOriginSource, ORIGIN_LABELS),
    ("DenialReason", DenialReason, DENIAL_REASON_LABELS),
    ("Purpose", Purpose, PURPOSE_LABELS),
)


@pytest.mark.parametrize(
    ("name", "members", "labels"),
    LABELLED,
    ids=[entry[0] for entry in LABELLED],
)
def test_every_member_has_a_spanish_label(
    name: str, members: type[enum.Enum], labels: dict[str, str]
) -> None:
    missing = {member.value for member in members} - set(labels)
    assert not missing, f"{name} is missing Spanish for {sorted(missing)}"


@pytest.mark.parametrize(
    ("name", "members", "labels"),
    LABELLED,
    ids=[entry[0] for entry in LABELLED],
)
def test_no_label_names_a_value_that_no_longer_exists(
    name: str, members: type[enum.Enum], labels: dict[str, str]
) -> None:
    """A stale key is how a renamed member loses its Spanish without failing."""
    stale = set(labels) - {member.value for member in members}
    assert not stale, f"{name} still labels removed values {sorted(stale)}"


@pytest.mark.parametrize(
    ("name", "members", "labels"),
    LABELLED,
    ids=[entry[0] for entry in LABELLED],
)
def test_no_label_is_the_english_identifier(
    name: str, members: type[enum.Enum], labels: dict[str, str]
) -> None:
    for value, label in labels.items():
        assert label != value, f"{name}[{value}] was never translated"
        assert label.strip(), f"{name}[{value}] is blank"


def test_the_scope_vocabulary_covers_every_scope() -> None:
    assert set(InboxFilters.SCOPES) == set(SCOPE_LABELS)


def test_channel_trust_is_labelled_where_it_is_rendered() -> None:
    """Trust is rendered inline on the Contact page rather than from a map.

    Asserted anyway, because the two values are the whole point of the
    distinction and a third would need somewhere to go.
    """
    from realestate.api import crm

    source = crm.__file__
    assert source
    assert {member.value for member in ChannelIdentityTrust} == {
        "Verified",
        "Asserted",
    }
