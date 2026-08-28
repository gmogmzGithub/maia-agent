"""Explainable, non-predictive matching of confirmed needs to Listings."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from realestate.domain.commercial.needs import (
    ECONOMIC_RANGE,
    ESSENTIAL_REQUIREMENTS,
    INTENT,
    SERVICE_AREA,
    NeedSnapshot,
)
from realestate.domain.text import fold_phrase

MATCH_RULE_VERSION = "inventory-match-v1"


@dataclass(frozen=True)
class ListingMatchInput:
    listing_id: uuid.UUID
    title: str
    public_location: str | None
    facts: Mapping[str, object]
    operations: tuple[str, ...]
    prices: tuple[Decimal, ...]


@dataclass(frozen=True)
class MatchExplanation:
    criterion: str
    expected: str
    observed: str
    result: str

    def as_dict(self) -> dict[str, str]:
        return {
            "criterion": self.criterion,
            "expected": self.expected,
            "observed": self.observed,
            "result": self.result,
        }


@dataclass(frozen=True)
class MatchProposal:
    listing_id: uuid.UUID
    eligible: bool
    kind: str | None
    rule_version: str
    explanation: tuple[MatchExplanation, ...]


_STOPWORDS = frozenset({"de", "del", "la", "el", "los", "las", "y", "en"})


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in fold_phrase(value).replace(",", " ").split()
        if len(token) > 2 and token not in _STOPWORDS
    }


def _money_range(value: str) -> tuple[Decimal, Decimal] | None:
    folded = fold_phrase(value)
    # ``fold_phrase`` deliberately removes punctuation for natural-language
    # matching; read amounts from the original so 3.5 million does not become
    # the two values 3 and 5.
    raw_numbers = re.findall(r"\d+(?:[.,]\d+)?", value.casefold())
    if not raw_numbers:
        return None
    values: list[Decimal] = []
    scale = Decimal("1000000") if "millon" in folded else Decimal("1")
    try:
        for raw in raw_numbers[:2]:
            values.append(Decimal(raw.replace(",", ".")) * scale)
    except InvalidOperation:
        return None
    if len(values) == 1:
        return values[0], values[0]
    return min(values), max(values)


def _integer_fact(facts: Mapping[str, object], *names: str) -> int | None:
    for name in names:
        value = facts.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float, Decimal)):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _minimum(text: str, *words: str) -> int | None:
    folded = fold_phrase(text)
    alternatives = "|".join(re.escape(fold_phrase(word)) for word in words)
    found = re.search(rf"(\d+)\s+(?:{alternatives})", folded)
    return int(found.group(1)) if found else None


class InventoryMatching:
    """One transparent rule set; no score, ranking model or hidden feature."""

    @classmethod
    def propose(
        cls,
        property_need: NeedSnapshot,
        listings: Sequence[ListingMatchInput],
    ) -> tuple[MatchProposal, ...]:
        return tuple(cls._one(property_need, listing) for listing in listings)

    @classmethod
    def _one(cls, need: NeedSnapshot, listing: ListingMatchInput) -> MatchProposal:
        explanation: list[MatchExplanation] = []

        if need.is_stale:
            explanation.append(
                MatchExplanation(
                    "vigencia",
                    "Necesidad confirmada en los últimos 90 días",
                    "Necesidad sin reconfirmar",
                    "Contradiction",
                )
            )
        if need.missing_required:
            explanation.append(
                MatchExplanation(
                    "criterios_confirmados",
                    "Criterios mínimos confirmados",
                    ", ".join(need.missing_required),
                    "Contradiction",
                )
            )

        intent = need.confirmed.get(INTENT, "")
        compatible = {
            "Buy": {"Sale", "Presale"},
            "Rent": {"Rental"},
        }.get(intent, set())
        observed_operations = set(listing.operations)
        operation_ok = bool(compatible & observed_operations)
        explanation.append(
            MatchExplanation(
                INTENT,
                intent or "Sin confirmar",
                ", ".join(listing.operations) or "Sin oferta",
                "Exact" if operation_ok else "Contradiction",
            )
        )

        area = need.confirmed.get(SERVICE_AREA, "")
        location = listing.public_location or ""
        expected_area = _tokens(area)
        observed_area = _tokens(location)
        if expected_area and expected_area <= observed_area:
            area_result = "Exact"
        elif expected_area & observed_area:
            area_result = "Approximate"
        else:
            area_result = "Contradiction"
        explanation.append(
            MatchExplanation(
                SERVICE_AREA, area, location or "No informada", area_result
            )
        )

        requested_range = _money_range(need.confirmed.get(ECONOMIC_RANGE, ""))
        if requested_range is None or not listing.prices:
            price_result = "Approximate"
        else:
            low, high = requested_range
            price = min(listing.prices)
            if low <= price <= high:
                price_result = "Exact"
            elif low * Decimal("0.9") <= price <= high * Decimal("1.1"):
                price_result = "Approximate"
            else:
                price_result = "Contradiction"
        explanation.append(
            MatchExplanation(
                ECONOMIC_RANGE,
                need.confirmed.get(ECONOMIC_RANGE, ""),
                ", ".join(str(value) for value in listing.prices) or "No informado",
                price_result,
            )
        )

        requirements = need.confirmed.get(ESSENTIAL_REQUIREMENTS, "")
        for criterion, words, fact_names in (
            ("recamaras", ("recamara", "recamaras"), ("bedrooms", "recamaras")),
            (
                "estacionamientos",
                ("estacionamiento", "estacionamientos"),
                ("parking_spaces", "estacionamientos"),
            ),
        ):
            minimum = _minimum(requirements, *words)
            if minimum is None:
                continue
            actual = _integer_fact(listing.facts, *fact_names)
            if actual is None:
                result = "Approximate"
            elif actual >= minimum:
                result = "Exact"
            else:
                result = "Contradiction"
            explanation.append(
                MatchExplanation(
                    criterion,
                    f"Mínimo {minimum}",
                    str(actual) if actual is not None else "No informado",
                    result,
                )
            )

        # Read back off the explanation rather than tracked beside it: the two
        # could disagree, and the explanation is what an operator is shown.
        results = {item.result for item in explanation}
        contradicted = "Contradiction" in results
        return MatchProposal(
            listing_id=listing.listing_id,
            eligible=not contradicted,
            kind=(
                None
                if contradicted
                else ("Approximate" if "Approximate" in results else "Exact")
            ),
            rule_version=MATCH_RULE_VERSION,
            explanation=tuple(explanation),
        )
