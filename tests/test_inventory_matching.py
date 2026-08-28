"""Pure, explainable inventory matching for Stage 7."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from realestate.db.models import PropertyNeedStatus
from realestate.domain.commercial.needs import NeedSnapshot
from realestate.domain.engagement.matching import (
    MATCH_RULE_VERSION,
    InventoryMatching,
    ListingMatchInput,
)


def need(*, status: PropertyNeedStatus = PropertyNeedStatus.ACTIVE) -> NeedSnapshot:
    return NeedSnapshot(
        need_id=uuid.uuid4(),
        status=status,
        confirmed={
            "transaction_intent": "Buy",
            "service_area": "Zapopan",
            "economic_range": "3.5 a 4.5 millones MXN",
            "horizon": "Tres meses",
            "essential_requirements": "3 recámaras y 2 estacionamientos",
        },
        pending={},
        last_confirmed_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def listing(
    *,
    operation: str = "Sale",
    location: str = "Zapopan",
    price: Decimal = Decimal("4000000"),
    facts: dict[str, object] | None = None,
) -> ListingMatchInput:
    return ListingMatchInput(
        listing_id=uuid.uuid4(),
        title="Casa sintética",
        public_location=location,
        facts=facts or {"bedrooms": 3, "parking_spaces": 2},
        operations=(operation,),
        prices=(price,),
    )


def test_exact_match_names_every_rule_and_version() -> None:
    proposal = InventoryMatching.propose(need(), (listing(),))[0]

    assert proposal.eligible is True
    assert proposal.kind == "Exact"
    assert proposal.rule_version == MATCH_RULE_VERSION
    assert {item.criterion for item in proposal.explanation} == {
        "transaction_intent",
        "service_area",
        "economic_range",
        "recamaras",
        "estacionamientos",
    }
    assert {item.result for item in proposal.explanation} == {"Exact"}


def test_approximate_match_is_visible_instead_of_hidden_in_a_score() -> None:
    proposal = InventoryMatching.propose(
        need(),
        (
            listing(
                location="Zapopan, Jalisco",
                price=Decimal("4800000"),
                facts={"bedrooms": 3},
            ),
        ),
    )[0]

    assert proposal.eligible is True
    assert proposal.kind == "Approximate"
    approximate = {
        item.criterion for item in proposal.explanation if item.result == "Approximate"
    }
    assert {"economic_range", "estacionamientos"} <= approximate


def test_known_contradiction_excludes_the_listing() -> None:
    proposal = InventoryMatching.propose(
        need(),
        (
            listing(
                operation="Rental",
                location="Monterrey",
                facts={"bedrooms": 2, "parking_spaces": 1},
            ),
        ),
    )[0]

    assert proposal.eligible is False
    assert proposal.kind is None
    assert "Contradiction" in {item.result for item in proposal.explanation}


def test_stale_or_incomplete_need_is_never_current_matching_truth() -> None:
    stale = InventoryMatching.propose(
        need(status=PropertyNeedStatus.STALE), (listing(),)
    )[0]
    incomplete_need = need()
    incomplete_need = NeedSnapshot(
        need_id=incomplete_need.need_id,
        status=incomplete_need.status,
        confirmed={
            key: value
            for key, value in incomplete_need.confirmed.items()
            if key != "horizon"
        },
        pending={"horizon": "Tal vez tres meses"},
        last_confirmed_at=incomplete_need.last_confirmed_at,
    )
    incomplete = InventoryMatching.propose(incomplete_need, (listing(),))[0]

    assert stale.eligible is False
    assert stale.explanation[0].criterion == "vigencia"
    assert incomplete.eligible is False
    assert any(
        item.criterion == "criterios_confirmados" for item in incomplete.explanation
    )


def test_reconfirmed_need_returns_to_current_matching_truth() -> None:
    stale_need = need(status=PropertyNeedStatus.STALE)
    reconfirmed = NeedSnapshot(
        need_id=stale_need.need_id,
        status=PropertyNeedStatus.ACTIVE,
        confirmed=stale_need.confirmed,
        pending={},
        last_confirmed_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    proposal = InventoryMatching.propose(reconfirmed, (listing(),))[0]

    assert proposal.eligible is True
    assert proposal.kind == "Exact"


def test_missing_and_single_value_facts_take_explicit_safe_branches() -> None:
    base = need()
    unusual = NeedSnapshot(
        need_id=base.need_id,
        status=base.status,
        confirmed={
            **base.confirmed,
            "service_area": "Centro Zapopan",
            "economic_range": "sin presupuesto confirmado",
            "essential_requirements": "3 recámaras y 2 estacionamientos",
        },
        pending={},
        last_confirmed_at=base.last_confirmed_at,
    )
    proposal = InventoryMatching.propose(
        unusual,
        (
            listing(
                location="Centro Guadalajara",
                price=Decimal("9000000"),
                facts={"bedrooms": True, "recamaras": "3", "parking_spaces": "2"},
            ),
        ),
    )[0]

    results = {item.criterion: item.result for item in proposal.explanation}
    assert results["service_area"] == "Approximate"
    assert results["economic_range"] == "Approximate"
    assert results["recamaras"] == "Exact"
    assert results["estacionamientos"] == "Exact"

    one_amount = NeedSnapshot(
        need_id=base.need_id,
        status=base.status,
        confirmed={**base.confirmed, "economic_range": "4 millones MXN"},
        pending={},
        last_confirmed_at=base.last_confirmed_at,
    )
    far = InventoryMatching.propose(
        one_amount, (listing(price=Decimal("7000000")),)
    )[0]
    assert any(
        item.criterion == "economic_range" and item.result == "Contradiction"
        for item in far.explanation
    )
