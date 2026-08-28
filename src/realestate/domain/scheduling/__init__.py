"""Advisor calendars, availability, and the visits booked against them.

Stage 0 booked visits against one Broker calendar because the operation had one
Advisor. PROJECT_MEMORY requires the other shape: *every appointment belongs
explicitly to an Advisor and uses that Advisor's availability*. That is what
this package owns.

Three seams, and what each one is the only way to do:

* :class:`~realestate.domain.scheduling.calendars.CalendarDirectory` — reach the
  calendar of one Advisor, and know when there is not one;
* :class:`~realestate.domain.scheduling.advisors.AdvisorScheduling` — ask what
  times an Advisor could actually receive a visit;
* :class:`~realestate.domain.scheduling.appointments.Appointments` — book,
  reschedule, cancel, and record what happened afterwards.

The rule that shapes all three is that authority is *authoritative*. An Advisor
with no configured calendar has no availability Product may quote, and a
calendar read that fails is not an empty calendar. Both are refusals. Offering a
time the operation cannot honour is worse than saying "no puedo confirmar
horarios ahora".
"""

from realestate.domain.scheduling.advisors import (
    AdvisorScheduling,
    SlotQuery,
    SlotsFound,
    SlotsUnavailable,
    Unavailable,
)
from realestate.domain.scheduling.appointments import (
    Appointments,
    BookVisit,
    CancelVisit,
    RecordVisitOutcome,
    RescheduleVisit,
    VisitBooked,
    VisitCancelled,
    VisitOutcome,
    VisitRefused,
)
from realestate.domain.scheduling.calendars import (
    CalendarDirectory,
    CalendarPort,
    GoogleCalendarDirectory,
)
from realestate.domain.scheduling.reminders import (
    REMINDER_POLICY_ACTIVATED,
    REMINDER_POLICY_VERSION,
    AppointmentReminders,
)

__all__ = [
    "AdvisorScheduling",
    "AppointmentReminders",
    "Appointments",
    "BookVisit",
    "CalendarDirectory",
    "CalendarPort",
    "CancelVisit",
    "GoogleCalendarDirectory",
    "REMINDER_POLICY_ACTIVATED",
    "REMINDER_POLICY_VERSION",
    "RecordVisitOutcome",
    "RescheduleVisit",
    "SlotQuery",
    "SlotsFound",
    "SlotsUnavailable",
    "Unavailable",
    "VisitBooked",
    "VisitCancelled",
    "VisitOutcome",
    "VisitRefused",
]
