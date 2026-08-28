# Stage 7 reactivation and Development campaigns

Stage 7 adds reviewed, bounded Marketing outreach without moving conversational
judgment or delivery authority out of their existing owners. Product proposes and
explains eligible work, an Administrator reviews it, and every accepted attempt
still passes through `OutboundMessaging.request`. Hermes only handles a Contact's
reply after Product has accepted that inbound message.

The operator surface is `/crm/reactivacion`. It is Mexican Spanish and exposes:

- provider-observed Message Template status, language, quality and exact body;
- explainable Listing-to-Property-Need reactivation candidates;
- explicit Development campaign criteria, exclusions and PII-safe audience
  references;
- dry-run and persisted audience results;
- frequency, audience and quiet-hour limits; and
- pause, cancel, denial and response outcomes.

There is no "send to all" path. A campaign names concrete Property Need IDs,
uses the versioned `development-audience-v1` resolver, and applies the same rules
for preview and activation. Inventory matching uses `inventory-match-v1` and
reports exact, approximate and contradictory criteria rather than a hidden score.
A stale need must be reconfirmed before either path is eligible.

## Authority and delivery boundary

An approved Development facts review must explicitly include
`marketing_authority_confirmed: true`. A Listing reactivation starts only from an
authorized Product catalog projection. Neither fact grants permission to contact
a person.

For each Contact, Product separately requires all of the following at request
time and again immediately before delivery:

1. no active suppression or opt-out;
2. current, evidence-bearing Marketing consent for `ListingMatches`,
   `DevelopmentAnnouncements`, or the broader `RealEstateMarketing` scope;
3. an exact Marketing template name and language observed as Approved from Meta
   within the last 24 hours;
4. unchanged static template content;
5. no intervening reply and no exceeded frequency cap; and
6. an active reviewed Candidate or Campaign under the applicable administrative
   stop lock.

Parameterized templates are denied in this stage because Product has no reviewed
parameter-binding interface. A pause or cancellation that commits before Meta
delivery quarantines queued work; a delivery that holds the lock first is
causally before the stop.

Candidate authorization, the outbound decision, Outbox row, audience result and
Marketing touch are written in one PostgreSQL transaction. A crash therefore
cannot record a touch without a queued message or create a message without its
eligibility evidence. Replies mark their originating Candidate or audience member
`Responded` and a later Opportunity preserves the Campaign origin.

## Current activation state

Real dispatch defaults to **Denied** through
`MARKETING_OUTBOUND_ACTIVATED=false`. The repository contains no legitimate
consent-capture path: SAN-010, an approved notice and evidence collection are
still open, and an Administrator cannot grant consent on a Contact's behalf.
WABA templates, account quality and sending capacity must be verified from the
real provider account before activation. Local fixture observations prove the
contract, not provider readiness.

The numeric defaults—one Marketing touch per 30 days, 20:00–09:00 quiet hours
in `America/Mexico_City`, 50 recipients per campaign—are conservative Product
rules, not claims about Mexican law or universal Meta limits. They require legal
and operational acceptance with real consented pilot data before the activation
flag may change.

See [the primary-source policy research](research/whatsapp-reactivation-campaigns.md)
for the provider classification and opt-in evidence behind the fail-closed design.

## Verification

The focused credential-free contract is:

```bash
docker compose exec product pytest \
  tests/test_inventory_matching.py \
  tests/test_message_template_registry.py \
  tests/test_engagement.py \
  tests/test_engagement_api.py \
  tests/test_engagement_migration.py
```

It covers matching explanations, stale needs, provider lifecycle, exact language
and content, consent scope, suppressions, dry runs, authorization, caps, quiet
hours, pause/cancel, delivery-time stops, retries, replies, attribution, PII-safe
UI and migration round trips. No test contacts Meta or sends a real message.
