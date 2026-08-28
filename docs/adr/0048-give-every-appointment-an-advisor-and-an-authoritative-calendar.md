---
status: accepted
---

# Give every appointment an Advisor and an authoritative calendar

Stage 0 booked visits against one Google Calendar, which was correct while the
operation had one person. PROJECT_MEMORY states the shape it needs instead:
*every appointment belongs explicitly to an Advisor and uses that Advisor's
availability*. A single global calendar makes that impossible to express — two
Advisors would be quoted each other's free time, and a visit would belong to
whoever happened to be configured.

Availability is therefore resolved through a calendar *directory*: one
service-account credential for the Organization, one calendar id per Advisor
stored on their member row. The seam is a port with a real Google adapter and a
test adapter, so nothing in the domain names the provider.

## Unconfigured is a refusal, not an empty week

The distinction this cut exists to make is between **busy** and **unknown**.

An Advisor whose calendar is genuinely full has no Available Slots, and that is
a successful answer. An Advisor with no `calendar_id`, or one whose calendar
could not be read, has no availability Product may quote at all. Both are
refusals with their own stable reason and their own Mexican Spanish sentence,
because the remedies differ: configure a calendar, end an absence, wait for the
provider. Collapsing them would tell a Contact "no hay horarios" when the truth
is "no pudimos consultar" — and offering times from an unreadable calendar would
send somebody to a house nobody is at.

A declared Advisor Absence is authority too, and it is Product's own. It
subtracts from availability like busy time, so an Advisor who told the
Administrator they are away does not become bookable because they forgot to
block their calendar.

## Who owns the visit, and who conducts it

The appointment's `advisor_id` is the Responsible Advisor, resolved by the same
deterministic assignment rule that owns every other "who is accountable"
question: preserve an existing owner, else the Property's present Property
Expert, else the configured default Advisor. Quoting availability reads that
rule without applying it — a Contact asking about times must not create a period
of responsibility — and booking applies it for real, so the times quoted and the
person who receives the visit cannot come from two different answers.

Booking is also the moment responsibility is *created* rather than merely
required. Stage 2 attaches an owner at Qualified; a Contact ready to see a house
has often not been formally qualified, and refusing the booking would be worse
than assigning the person the rule already names. A confirmed visit is stronger
evidence than qualification, so the rule runs and a queued outcome — nobody
eligible — refuses the booking with the reason carried through.

`conducting_advisor_id` is the ADR-0037 case: a Property Expert conducts a visit
instead of the owner *only when that is made explicit*. Set it and the expert's
calendar is the one that must be free, because they are the person who will be
standing at the door. NULL means the owner conducts it; it never means unknown.

## Per-Advisor schedules are not invented here

The Weekly Bookable Schedule, the 90-minute duration and the booking horizon
stay Organization-wide configuration. SAN-031 and SAN-032 are unanswered, and a
per-person schedule Product made up would be worse than one the operation has
already agreed on. An Advisor expresses their own limits as busy time in their
authoritative calendar — exactly what PROJECT_MEMORY says they do for travel.

## Existing appointments keep no owner

Every appointment booked before this cut has none, and inventing one would
attribute a visit to somebody who never agreed to it. `advisor_id` stays NULL on
those rows, Product refuses to treat them as bookable work, and the CRM Calendar
surfaces them to an Administrator as requiring a decision.

Reconciling one still works, because a pre-Stage-3 event can only be on the
single calendar the operation had — which is now the default Advisor's. That is
not a guess about where the event might be; it is the only place it can be.
Stage 0's `GOOGLE_CALENDAR_ID` therefore becomes the default Advisor's calendar
when no per-login mapping names them, so an existing local setup keeps booking
instead of quietly losing its authority.
