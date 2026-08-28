"""Who is asking, and what that entitles them to see or change.

Every commercial entry point takes an :class:`Actor`. That is the whole reason
organization scoping and role authority do not have to be restated in each
router, query and template: the modules below this one accept an Actor and
refuse to answer outside it.

Authentication is unchanged from Stage 0 — HTTP Basic against the configured
operational credentials. What is new is that the authenticated username is
resolved to an :class:`~realestate.db.models.OrganizationMember` row, so a
credential that exists in the environment but has no member record is refused
rather than treated as an implicit administrator.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from realestate.db.models import MemberRole


class Authority(str, enum.Enum):
    """What the caller is allowed to reach.

    ``PRODUCT`` is Product's own deterministic work — the webhook path, the
    background loop, a migration follow-up. It is organization-scoped like
    everybody else, and it is deliberately *not* an administrator: it cannot
    mark an Opportunity Won, because ADR-0032 reserves that for a human who
    accepted evidence.
    """

    ADMINISTRATOR = "OrganizationAdministrator"
    ADVISOR = "RealEstateAdvisor"
    PRODUCT = "Product"


class CommercialError(Exception):
    """Base class for a refusal the commercial modules issue deliberately.

    Every subclass carries Mexican Spanish text, because every one of them can
    reach an operator's screen. A message an operator cannot read is not an
    error report, it is a stack trace with extra steps.
    """

    #: Mexican Spanish, operator-facing.
    message: str = "No se pudo completar la operación."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class NotAuthorized(CommercialError):
    """The Actor may not perform or see this."""

    message = "No tienes permiso para realizar esta acción."


class UnknownMember(CommercialError):
    """The credential authenticated but no Organization member matches it."""

    message = (
        "Tu usuario está autenticado pero no pertenece a ninguna organización. "
        "Pide a un administrador que te dé de alta."
    )


class NotFound(CommercialError):
    """The record does not exist, or does not exist for this Actor.

    Deliberately one error for both. Telling an Advisor that an Opportunity
    exists but belongs to somebody else already leaks the organization's
    pipeline shape.
    """

    message = "No encontramos ese registro."


class InvalidTransition(CommercialError):
    """The requested commercial stage change is not allowed from here."""

    message = "Ese cambio de etapa no está permitido."


class QualificationIncomplete(CommercialError):
    """Qualified was requested while material criteria are still Pending."""

    message = (
        "Faltan criterios mínimos confirmados para calificar esta oportunidad."
    )


class MissingEvidence(CommercialError):
    """A terminal outcome was requested without the evidence it requires."""

    message = "Falta la evidencia requerida para registrar este resultado."


class DuplicateCommand(CommercialError):
    """The same command key was recorded concurrently by another transaction.

    Propagated rather than swallowed. The loser has already applied its own
    mutations to the session, so it cannot quietly adopt the winner's answer —
    its whole transaction has to be discarded. Being a
    :class:`CommercialError` is what makes that discard produce a sentence an
    operator can read instead of a 500.
    """

    message = "Esa operación ya se había registrado."

    def __init__(self, command_key: str) -> None:
        self.command_key = command_key
        super().__init__()


@dataclass(frozen=True)
class Actor:
    """One authenticated caller, resolved to an Organization and an authority.

    Constructed by :mod:`realestate.domain.commercial.organization`, never by a
    router assembling fields by hand: an Actor that a caller could build
    freely would make the authority checks below advisory.
    """

    organization_id: uuid.UUID
    authority: Authority
    #: The member row, when a human is acting. ``None`` for Product's own work.
    member_id: uuid.UUID | None
    #: Audit identity. A login for a human, a subsystem name for Product.
    label: str
    display_name: str

    @property
    def actor_type(self) -> str:
        """The ``audit_events.actor_type`` this caller writes history under."""
        return "Product" if self.authority is Authority.PRODUCT else "OrganizationMember"

    @property
    def is_administrator(self) -> bool:
        return self.authority is Authority.ADMINISTRATOR

    @property
    def is_product(self) -> bool:
        return self.authority is Authority.PRODUCT

    @property
    def sees_whole_operation(self) -> bool:
        """Whether unassigned and other Advisors' work is visible.

        An Administrator sees the whole initial operation (PROJECT_MEMORY). So
        does Product, because the deterministic paths — assignment, dormancy,
        retention — have to reach records nobody owns yet; that is the point of
        the Assignment Queue.
        """
        return self.authority in (Authority.ADMINISTRATOR, Authority.PRODUCT)

    def require_administrator(self) -> None:
        """Refuse anything reserved to an Organization Administrator."""
        if not self.is_administrator:
            raise NotAuthorized(
                "Sólo un administrador de la organización puede realizar esta acción."
            )

    def require_same_organization(self, organization_id: uuid.UUID) -> None:
        """Refuse a record from another Organization as if it did not exist."""
        if organization_id != self.organization_id:
            raise NotFound()

    def require_owns(self, member_id: uuid.UUID | None, message: str) -> None:
        """Refuse a record this Actor is not responsible for.

        An Administrator and Product see the whole operation, so the check is a
        no-op for them. For an Advisor it is the second half of the visibility
        rule, and it lives here rather than in each module because "who may see
        this" is the Actor's own question — three copies of it drifted apart
        once already.
        """
        if self.sees_whole_operation:
            return
        if member_id is None or member_id != self.member_id:
            raise NotFound(message)

    @classmethod
    def product(cls, organization_id: uuid.UUID, subsystem: str) -> Actor:
        """Product acting on its own behalf inside one Organization."""
        return cls(
            organization_id=organization_id,
            authority=Authority.PRODUCT,
            member_id=None,
            label=subsystem,
            display_name="Maia",
        )


def authority_for(role: str) -> Authority:
    """The Authority a stored member role grants."""
    return (
        Authority.ADMINISTRATOR
        if role == MemberRole.ADMINISTRATOR.value
        else Authority.ADVISOR
    )
