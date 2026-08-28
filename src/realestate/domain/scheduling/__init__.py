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
