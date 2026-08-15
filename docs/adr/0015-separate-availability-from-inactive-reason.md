---
status: accepted
---

# Separate availability from the reason for inactivity

A Property has one operational availability state, Active or Inactive, so Maia has a
single deterministic gate for customer disclosure and new bookings. An Inactive
Property separately records why it is unavailable as Sold, Rented, Reserved,
Temporarily Unavailable, Withdrawn, or Unspecified. This avoids scattering the same
safety rule across several terminal-looking statuses while preserving precise
administrative meaning; authorized corrections and reactivation remain auditable.
Making a Property Inactive blocks new activity immediately but never cancels an
existing confirmed visit; each affected visit becomes an Inactive Appointment Review
for an Administrator to resolve.
