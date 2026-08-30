---
status: accepted
---

# Run three named Deployment Environments and withhold discovery until the last

Maia will run in exactly three named installations — **Sandbox**, **Pilot**,
**Public** — and only Public is reachable by organic discovery. Sandbox runs on
the founder's always-on Mac mini behind a Cloudflare Tunnel with no purchased
hosting, holds synthetic Contacts, and serves the operator surfaces behind
Cloudflare Access in addition to the existing credential. Pilot runs on one small
AWS host, holds real Contacts and real leads from Santiago's Meta ads, and is
served from a subdomain of the Platform Vendor's own domain rather than from a
brokerage domain, because the brand name is not yet settled and an indexed
throwaway hostname is expensive to unwind. Public moves the public site to the
Brokerage Brand's own domain and is the first environment permitted to publish a
sitemap.

Two rules carry more weight than the hosting choices and are the reason this is an
ADR rather than a paragraph in a runbook.

**No provider identity is ever shared between environments.** A WhatsApp phone
number has one webhook callback URL, a Meta app has one callback URL per product,
and a Telegram bot token has one poller. Sharing any of them does not degrade —
it silently misroutes, so a real lead lands in a test database or vanishes while
Product, Hermes and every credential report healthy. Each environment therefore
has its own WhatsApp identity, its own Meta app, its own bot, its own model key
and its own calendars. Maia's WhatsApp number is dedicated and cannot exist in
the WhatsApp consumer app at all, which is why a human answering as themself does
so in `/crm` under Conversation Handling Mode (ADR-0029) rather than from a phone.

**Discovery is a publication decision, not a crawler's decision.** ADR-0041
treats organic discovery as a publication contract, so withholding an environment
from it belongs beside the other publication rules: Sandbox and Pilot serve a
site-wide `noindex` and refuse a sitemap by default, and an environment becomes
discoverable only by explicit setting.

## Considered options

Buying the Brokerage Brand's domain now and running Pilot on it was rejected
because the brand name is pending trademark clearance and the project and agent
names may still change; the cost of deferring is one deliberate cutover, and the
cost of guessing is a brand domain we abandon. Deploying Pilot on ECS Fargate
with RDS was rejected as premature: it answers no question Pilot exists to ask,
costs several times the single host, and delays the first real lead by weeks. A
non-AWS VPS was rejected not on price but because Pilot holds real personal data
and a later provider move would be a second live migration.

## Consequences

Pilot starts from an empty database provisioned through a Provisioning Run
(ADR-0055) rather than from a Sandbox dump, so no synthetic Contact can ever be
mistaken for a real one. Both non-public environments run single-instance, with a
brief deploy interruption covered by Meta's webhook retries. The public site's
move to the Brokerage Brand's domain is a deferred, deliberate cutover with its
own decision, and until it happens the brokerage's customer-facing site lives on
a subdomain of a personal domain — which is the fact a future reader is most
likely to question, and is intentional.
