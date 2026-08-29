"""Who may operate the platform, as distinct from who may operate a brokerage.

:class:`~realestate.domain.commercial.actors.Actor` answers "who is asking, and
what may they see inside their Organization". It cannot answer platform
questions, and extending it to try would be the wrong shape: an ``Actor`` carries
an ``organization_id``, and the whole point of a platform command is that it
either has no Organization yet (provisioning) or is deliberately *about* one from
outside (a support grant, a deletion).

So platform commands take a :class:`PlatformOperator` instead. It is not a role
inside any Organization, it grants no read access to any Organization's data, and
it is authenticated by its own credential rather than by an Organization member
row. The three properties that matter:

* **it cannot read customer data.** A ``PlatformOperator`` is accepted by
  provisioning, configuration, entitlements, credentials, usage and the data
  lifecycle. It is refused by every commercial, catalog, conversation and
  analytics surface, which take an ``Actor``. To read an Organization's records,
  an internal engineer needs a
  :mod:`~realestate.domain.platform.support` grant, which is temporary, explained
  and audited — see ADR-0054;
* **it writes history as ``Platform``.** ``audit_events.actor_type`` is the one
  value the table's check constraint allows without an Organization, and it is
  reserved for exactly this;
* **every mutation it performs names a reason.** Not decoration: the commands
  below all require one, because "somebody with the platform token changed this"
  is not an explanation anybody can act on months later.
"""

from __future__ import annotations

from dataclasses import dataclass

from realestate.domain.commercial.actors import CommercialError


class PlatformNotAuthorized(CommercialError):
    """A platform command was attempted without platform authority."""

    message = (
        "Esta operación pertenece a la administración de la plataforma y "
        "requiere una credencial de operador de plataforma."
    )


class ReasonRequired(CommercialError):
    """A platform mutation arrived without a written reason.

    Enforced rather than encouraged. A configuration change, an entitlement
    change, a support grant and a deletion are all things somebody will ask
    about later, and the answer cannot be reconstructed from the diff.
    """

    message = (
        "Toda operación de plataforma requiere un motivo escrito. Explica por "
        "qué se hace este cambio."
    )


#: The shortest reason worth storing. Below this the field is a formality, and a
#: formality in an audit trail is worse than an empty one because it looks like
#: evidence.
MINIMUM_REASON_LENGTH = 12


@dataclass(frozen=True)
class PlatformOperator:
    """One authenticated internal operator of the managed platform.

    Constructed only by :func:`realestate.api.platform.require_platform_operator`
    from a dedicated credential, never assembled by a domain module: an operator
    a caller could build freely would make every check below advisory.
    """

    #: The audit identity. A person's login, or a named automation.
    label: str
    #: What the operator is doing this session, for the audit trail.
    display_name: str = "Operador de plataforma"

    @property
    def actor_type(self) -> str:
        """The ``audit_events.actor_type`` a platform action writes under."""
        return "Platform"


def require_reason(reason: str) -> str:
    """The reason, normalised, or a refusal."""
    text = " ".join(reason.split())
    if len(text) < MINIMUM_REASON_LENGTH:
        raise ReasonRequired()
    return text
