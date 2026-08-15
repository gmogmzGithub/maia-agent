"""Administrative operations on Property Status (P-065, P-066, ADR-0009).

The Administrative Role may inspect the inventory and move a Property between
the two Stage 0 statuses. Everything consequential lives here rather than in the
Model: authorisation comes from the trusted session binding, the transition is
persisted and audited with the originating message, and the returned result is
the fact the Agent reports.

Deactivation never cancels anything. It blocks *new* Sales disclosure and *new*
bookings and reports how many Confirmed Appointments now need administrative
review (P-017).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    InactiveReviewStatus,
    Property,
    PropertyInactiveReason,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.properties import (
    MAX_PROPERTIES,
    accepted_version,
    resolve_property,
)

VALID_STATUSES = (PropertyStatus.ACTIVE.value, PropertyStatus.INACTIVE.value)
VALID_INACTIVE_REASONS = tuple(reason.value for reason in PropertyInactiveReason)


@dataclass(frozen=True)
class Administrator:
    """Trusted actor identity, derived from the session binding — never a model argument."""

    actor_id: str
    origin_message_id: str | None = None


class AdministrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_property_status(
        self,
        reference: str,
        status: str,
        actor: Administrator,
        inactive_reason: str | None = None,
    ) -> dict:
        """Move one Property between `Active` and `Inactive`.

        Repeating the current status is idempotent and returns ``unchanged``
        without writing a transition.
        """
        if status not in VALID_STATUSES:
            # The schema constrains this too; this is the backstop.
            return {"result": "ambiguous", "detail": "status must be Active or Inactive"}
        if status == PropertyStatus.INACTIVE.value:
            if inactive_reason not in VALID_INACTIVE_REASONS:
                return {
                    "result": "ambiguous",
                    "detail": (
                        "inactive_reason is required for Inactive and must be one of "
                        + ", ".join(VALID_INACTIVE_REASONS)
                    ),
                }
        elif inactive_reason is not None:
            return {
                "result": "ambiguous",
                "detail": "inactive_reason must be omitted when status is Active",
            }

        prop = await resolve_property(self._session, reference)
        if prop is None:
            return {"result": "not_found"}

        previous = prop.status
        previous_reason = prop.inactive_reason
        target_reason = (
            inactive_reason if status == PropertyStatus.INACTIVE.value else None
        )
        changed = previous != status or previous_reason != target_reason

        if changed:
            prop.status = status
            prop.inactive_reason = target_reason
            affected = await self.confirmed_appointments(prop)
            if status == PropertyStatus.INACTIVE.value:
                await self._open_inactive_reviews(prop)
            await self._audit(
                actor,
                action="PropertyStatusChanged",
                property_key=prop.property_key,
                details={
                    "previous_status": previous,
                    "previous_inactive_reason": previous_reason,
                    "requested_status": status,
                    "requested_inactive_reason": target_reason,
                    "result": "updated",
                    "affected_confirmed_appointments": affected,
                },
            )
        else:
            affected = 0
            await self._audit(
                actor,
                action="PropertyStatusUnchanged",
                property_key=prop.property_key,
                details={
                    "requested_status": status,
                    "requested_inactive_reason": target_reason,
                    "result": "unchanged",
                },
            )

        # One shape for both outcomes: repeating the current status reports the
        # same fields, with the current values simply equal to the previous ones.
        return {
            "result": "updated" if changed else "unchanged",
            "property_id": prop.property_key,
            "name": prop.name,
            "previous_status": previous,
            "previous_inactive_reason": previous_reason,
            "current_status": prop.status,
            "current_inactive_reason": prop.inactive_reason,
            # Deactivation starts administrative review; it never cancels (P-017).
            "affected_confirmed_appointments": affected,
        }

    async def list_properties(self) -> dict:
        """Compact inventory for an administrator. No document prose (P-066)."""
        rows = (
            await self._session.execute(
                select(Property).order_by(Property.property_key).limit(MAX_PROPERTIES)
            )
        ).scalars().all()

        # Counted for the whole inventory in one grouped query rather than once
        # per row: this runs on every administrative overview and page load.
        counts = await self._confirmed_appointment_counts()
        properties = []
        for prop in rows:
            record = await accepted_version(self._session, prop)
            metadata: dict = record.document_metadata if record else {}
            properties.append(
                {
                    "property_id": prop.property_key,
                    "name": prop.name,
                    "status": prop.status,
                    "inactive_reason": prop.inactive_reason,
                    "document_version": record.version if record else 0,
                    "property_type": metadata.get("property_type"),
                    "operation": metadata.get("operation"),
                    "price_amount": metadata.get("price_amount"),
                    "price_currency": metadata.get("price_currency"),
                    "updated_at": prop.updated_at.isoformat(),
                    "confirmed_appointments": counts.get(prop.id, 0),
                }
            )
        return {"result": "found", "properties": properties}

    async def list_active_properties_for_sales(self) -> dict:
        """Active, customer-safe inventory summaries for the Sales Role.

        Sales may answer an explicit request for available options, but must not
        see inactive inventory or operational details such as appointment counts.
        Full facts still require the role-aware ``get_property_information``
        operation for a named Property.
        """
        rows = (
            await self._session.execute(
                select(Property)
                .where(Property.status == PropertyStatus.ACTIVE.value)
                .order_by(Property.property_key)
                .limit(MAX_PROPERTIES)
            )
        ).scalars().all()

        properties = []
        for prop in rows:
            record = await accepted_version(self._session, prop)
            metadata: dict = record.document_metadata if record else {}
            properties.append(
                {
                    "property_id": prop.property_key,
                    "name": prop.name,
                    "property_type": metadata.get("property_type"),
                    "operation": metadata.get("operation"),
                    "price_amount": metadata.get("price_amount"),
                    "price_currency": metadata.get("price_currency"),
                }
            )
        return {"result": "found", "properties": properties}

    async def confirmed_appointments(self, prop: Property) -> int:
        """Count future Confirmed Appointments affected by deactivation."""
        return int(
            (
                await self._session.execute(
                    self._confirmed_query(select(func.count(Appointment.id))).where(
                        Appointment.property_uuid == prop.id
                    )
                )
            ).scalar_one()
        )

    async def _confirmed_appointment_counts(self) -> dict[uuid.UUID, int]:
        """The same count as ``confirmed_appointments``, for every Property."""
        rows = await self._session.execute(
            self._confirmed_query(
                select(Appointment.property_uuid, func.count(Appointment.id))
            ).group_by(Appointment.property_uuid)
        )
        return {property_uuid: int(total) for property_uuid, total in rows}

    @staticmethod
    def _confirmed_query(statement):  # noqa: ANN001, ANN205
        """The one definition of "a future Confirmed Appointment"."""
        return statement.where(
            Appointment.status == AppointmentStatus.CONFIRMED.value
        ).where(Appointment.starts_at > func.now())

    async def _open_inactive_reviews(self, prop: Property) -> None:
        """Make every affected visit visible without cancelling it (P-017)."""
        rows = (
            (
                await self._session.execute(
                    self._confirmed_query(select(Appointment))
                    .where(Appointment.property_uuid == prop.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.inactive_review_status is None:
                row.inactive_review_status = InactiveReviewStatus.PENDING.value

    async def _audit(
        self, actor: Administrator, *, action: str, property_key: str, details: dict
    ) -> None:
        # P-065: an administrative mutation always carries the message it came from.
        await record_audit(
            self._session,
            actor_type="Administrative",
            actor_id=actor.actor_id,
            action=action,
            subject_id=property_key,
            details={**details, "origin_message_id": actor.origin_message_id},
        )
