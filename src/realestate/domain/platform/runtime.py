"""Versioned operating policy resolved for exactly one Organization."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.availability import ScheduleError, WeeklySchedule
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.configuration import OrganizationConfiguration


class OrganizationPolicyInvalid(CommercialError):
    message = (
        "La configuración operativa de esta organización está incompleta o no "
        "es válida. Corrige scheduling antes de atender citas."
    )


class OrganizationAppointmentPolicies:
    """Materialize appointment policy from one Organization's current version.

    The founding Organization may use the reviewed process policy while its
    historical configuration document is brought up to date. Every other
    Organization must name its own zone, complete seven-day schedule and visit
    duration; it never inherits those values from Larevia's environment.
    """

    def __init__(
        self,
        bootstrap_policy: AppointmentPolicy,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
    ) -> None:
        self._bootstrap_policy = bootstrap_policy
        self._bootstrap_organization_id = bootstrap_organization_id
        self._cache: dict[uuid.UUID, tuple[str, AppointmentPolicy]] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> AppointmentPolicy:
        view = await OrganizationConfiguration(
            session,
            bootstrap_organization_id=self._bootstrap_organization_id,
        ).current(organization_id)
        cached = self._cache.get(organization_id)
        if cached is not None and cached[0] == view.checksum:
            return cached[1]

        scheduling = view.section("scheduling")
        bootstrap = organization_id == self._bootstrap_organization_id
        policy = self._materialize(scheduling, bootstrap=bootstrap)
        self._cache[organization_id] = (view.checksum, policy)
        return policy

    def _materialize(
        self, scheduling: Mapping[str, object], *, bootstrap: bool
    ) -> AppointmentPolicy:
        base = self._bootstrap_policy
        zone = self._text(
            scheduling,
            "time_zone",
            fallback=base.schedule.timezone if bootstrap else None,
        )
        weekly = self._text(
            scheduling,
            "weekly_schedule",
            fallback=self._weekly_spec(base.schedule) if bootstrap else None,
        )
        visit_minutes = self._integer(
            scheduling,
            "visit_minutes",
            fallback=base.visit_minutes if bootstrap else None,
            minimum=30,
            maximum=8 * 60,
        )
        horizon_days = self._integer(
            scheduling,
            "booking_horizon_days",
            fallback=base.horizon_days,
            minimum=1,
            maximum=90,
        )
        max_candidates = self._integer(
            scheduling,
            "max_slot_candidates",
            fallback=base.max_candidates,
            minimum=1,
            maximum=30,
        )
        reminder_hour = self._integer(
            scheduling,
            "appointment_day_of_reminder_hour",
            fallback=base.day_of_reminder_hour,
            minimum=0,
            maximum=23,
        )
        try:
            schedule = WeeklySchedule.parse(weekly, zone)
        except (ScheduleError, ValueError) as exc:
            raise OrganizationPolicyInvalid(
                f"La configuración scheduling no es válida: {exc}"
            ) from exc
        return AppointmentPolicy(
            schedule=schedule,
            visit_minutes=visit_minutes,
            horizon_days=horizon_days,
            max_candidates=max_candidates,
            day_of_reminder_hour=reminder_hour,
            event_title=base.event_title,
        )

    @staticmethod
    def _text(
        values: Mapping[str, object], name: str, *, fallback: str | None
    ) -> str:
        value = values.get(name, fallback)
        if not isinstance(value, str) or not value.strip():
            raise OrganizationPolicyInvalid(
                f"La configuración scheduling debe incluir {name}."
            )
        return value.strip()

    @staticmethod
    def _integer(
        values: Mapping[str, object],
        name: str,
        *,
        fallback: int | None,
        minimum: int,
        maximum: int,
    ) -> int:
        value = values.get(name, fallback)
        if isinstance(value, bool) or not isinstance(value, int):
            raise OrganizationPolicyInvalid(
                f"La configuración scheduling debe incluir {name} como entero."
            )
        if not minimum <= value <= maximum:
            raise OrganizationPolicyInvalid(
                f"La configuración scheduling.{name} debe estar entre "
                f"{minimum} y {maximum}."
            )
        return value

    @staticmethod
    def _weekly_spec(schedule: WeeklySchedule) -> str:
        days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        chunks: list[str] = []
        for index, day in enumerate(days):
            ranges = schedule.ranges.get(index, ())
            value = ",".join(
                f"{item.start:%H:%M}-{item.end:%H:%M}" for item in ranges
            )
            chunks.append(f"{day}={value or 'nada'}")
        return ";".join(chunks)
