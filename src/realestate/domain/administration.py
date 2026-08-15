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

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    InactiveReviewStatus,
    Property,
    PropertyDocumentVersion,
    PropertyInactiveReason,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.properties import MAX_PROPERTIES, resolve_property

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
        if previous == status and previous_reason == target_reason:
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
            return {
                "result": "unchanged",
                "property_id": prop.property_key,
                "name": prop.name,
                "previous_status": previous,
                "previous_inactive_reason": previous_reason,
                "current_status": prop.status,
                "current_inactive_reason": prop.inactive_reason,
                "affected_confirmed_appointments": 0,
            }

        prop.status = status
        prop.inactive_reason = target_reason
        affected = await self._confirmed_appointments(prop)
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

        return {
            "result": "updated",
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

        properties = []
        for prop in rows:
            version = 0
            metadata: dict = {}
            if prop.accepted_version_id is not None:
                record = await self._session.get(
                    PropertyDocumentVersion, prop.accepted_version_id
                )
                version = record.version if record else 0
                metadata = record.document_metadata if record else {}
            properties.append(
                {
                    "property_id": prop.property_key,
                    "name": prop.name,
                    "status": prop.status,
                    "inactive_reason": prop.inactive_reason,
                    "document_version": version,
                    "property_type": metadata.get("property_type"),
                    "operation": metadata.get("operation"),
                    "price_amount": metadata.get("price_amount"),
                    "price_currency": metadata.get("price_currency"),
                    "updated_at": prop.updated_at.isoformat(),
                    "confirmed_appointments": await self._confirmed_appointments(prop),
                }
            )
        return {"result": "found", "properties": properties}

    async def _confirmed_appointments(self, prop: Property) -> int:
        """Count future Confirmed Appointments affected by deactivation."""
        return int(
            (
                await self._session.execute(
                    select(func.count(Appointment.id))
                    .where(Appointment.property_uuid == prop.id)
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.starts_at > func.now())
                )
            ).scalar_one()
        )

    async def _open_inactive_reviews(self, prop: Property) -> None:
        """Make every affected visit visible without cancelling it (P-017)."""
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.property_uuid == prop.id)
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.starts_at > func.now())
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
