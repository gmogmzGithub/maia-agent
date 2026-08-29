---
status: accepted
---

# Carry the Organization on every row and refuse unbound channels

Every table holding a Brokerage Organization's data will name that Organization in
an `organization_id` column with a composite foreign key agreeing with its parent,
every business key that was globally unique becomes unique per Organization, and
every inbound identifier — WhatsApp phone number, Telegram bot, public hostname —
resolves through an explicit channel binding whose absence is a refusal rather
than a default to the founding Organization. A written scoping table classifies
each table as Organization data or deliberately platform-wide with a reason, and a
test refuses an unclassified one. This costs a wide migration and a redundant
column, and it buys the property the managed platform is sold on: a query that
forgets its scope fails a test instead of answering with somebody else's
brokerage, and a misdirected channel is an operator error instead of a silent
cross-organization write nobody discovers until the customer does.
