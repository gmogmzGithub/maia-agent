"""Versioned integration boundary with the upstream Hermes Runtime.

Only this package knows the Hermes wire contract. Domain code must not import
Hermes internals or this module's transport details (ADR-0003, ADR-0008).
"""

from realestate.hermes.client import (
    REQUIRED_METHODS,
    HermesClient,
    HermesHealth,
    HermesStatus,
    HermesUnavailable,
)

__all__ = [
    "REQUIRED_METHODS",
    "HermesClient",
    "HermesHealth",
    "HermesStatus",
    "HermesUnavailable",
]
