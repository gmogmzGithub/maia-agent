# Domain Modules

This package is Maia's Product authority.

Put business decisions here: authorization, state transitions, invariants,
eligibility, idempotency, audit outcomes, retention decisions, and rules that
must be true no matter whether the caller is an HTTP route, Hermes tool, worker,
or future operator surface.

Prefer product-area subpackages over generic buckets:

- `commercial/`: Contacts, Opportunities, assignment, next actions, handling,
  team operations, and CRM read models.
- `platform/`: Organizations, provisioning, channel routing, credentials,
  entitlements, support grants, lifecycle, imports, and usage.
- `catalog/`: authoritative listings, media, offers, and presentation policy.
- `public/`: public-site contracts, saved collections, handoff, analytics, and
  publication rules.
- `external_inventory/`: read-only external inventory and revalidation.
- `engagement/`: consent, audiences, template observations, reactivation, and
  campaigns.
- `analytics/`: event taxonomy, pseudonymization, projection, traffic, and
  metrics.
- `sponsorship/`: paid visibility, capacity, delivery, pricing, reporting, and
  buyer sharing.
- `scheduling/`: advisor availability, calendars, appointments, reminders, and
  handoff.
