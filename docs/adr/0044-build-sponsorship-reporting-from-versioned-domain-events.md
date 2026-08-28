---
status: accepted
---

# Build sponsorship reporting from versioned domain events

Sponsorship reporting has three views over common definitions: an Administrator
dashboard for operations, revenue, capacity, and data quality; a presale
presentation using safe historical comparables; and a campaign-scoped buyer report
delivered by revocable expiring link and PDF. A sponsorship buyer does not receive
a CRM account in the MVP.

The official funnel is Visible Impression, Listing open, Gallery open,
Significant Gallery Exploration, saved or shared, Maia start, WhatsApp handoff,
appointment request, verified appointment, attended appointment, and known
Opportunity outcome. A Visible Impression initially requires 50 percent of the
card for one second; Significant Gallery Exploration requires five photographs or
30 percent of the gallery. Product stores versioned definitions so historic
reports remain reproducible.

Presale evidence groups comparable operation, municipality, property type,
Commercial Price Band, Presentation Tier, and sponsored surface. Reports disclose
period, sample size, median, and range and explicitly identify insufficient
history. Attribution reports view-through outcomes for up to seven days and
engaged outcomes for up to 90 days without overwriting first Opportunity Origin or
claiming causal lift.

Buyer views contain only aggregate campaign delivery, interaction, outcomes, and
their own price and unit economics. They exclude Contact identity, phone numbers,
conversation content, individual searches, and Saved Collections. Internal views
add commercial terms, payment state, inventory capacity, revenue, invalid traffic,
and Follow-up Data Completeness. Missing outcomes remain `Sin registrar`.

Product emits immutable idempotent analytics events through its durable Outbox.
The MVP stores pseudonymous event records in a separate PostgreSQL analytics schema
and calculates versioned aggregates and materialized views. A dedicated warehouse
is deferred until scale justifies replication. Event-level and aggregate retention
remain an explicit privacy and legal decision rather than inheriting conversation
retention accidentally.
