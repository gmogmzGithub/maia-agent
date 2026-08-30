# Maia Agent - Development Guide

Instructions for AI coding assistants and developers working on this repository.

## Product Identity

The product name is **Maia**.

Maia is a Hermes-backed real estate lead agent. It handles WhatsApp inquiries,
answers from approved property documents, schedules visits, and coordinates
follow-ups. The product should feel like a capable real estate operator, not an
AI novelty.

## Public Repository Rule

This repository is intended to be public and recruiter-visible.

Do not commit:

- raw Codex memory files or session transcripts;
- Docker volumes containing local Hermes or PostgreSQL runtime state;
- `.env`, tokens, credentials, or provider keys;
- real lead data, real customer conversations, or private property documents;
- private planning notes that are not meant for hiring managers;
- generated databases, lock files, caches, or local artifacts.

Use `PROJECT_MEMORY.md` for curated project decisions that are safe to publish.
Put private notes outside this repository or on a private branch that is never
merged into `main`.

## Architecture Boundary

Preserve the Product/Hermes split.

Hermes owns:

- natural-language understanding;
- session continuity;
- fragmented-message reconciliation;
- clarification;
- time interpretation;
- tool selection;
- response composition.

Maia owns:

- trusted identity;
- PostgreSQL truth;
- Inbox/Outbox state;
- authorization;
- deterministic business policy;
- audit events;
- Calendar and Meta side effects;
- retries, ambiguity handling, and safety outcomes.

The model may request operations through typed tools. It must not directly own
database writes, Calendar credentials, WhatsApp delivery, or business truth.

## Organizational Boundary

Since Stage 9 the product serves several Brokerage Organizations. One rule holds
everywhere and has no exceptions for convenience:

**No operation reaches across Organizations.**

In practice, when you touch this codebase:

- every table holding an Organization's data names it in an `organization_id`
  column. `src/realestate/domain/platform/scoping.py` says which tables those
  are, and a test refuses a table missing from it — so a new table needs an entry
  there, with a reason if it is deliberately platform-wide;
- a query filters on `organization_id` unless it is keyed on an opaque identifier
  that already belongs to exactly one Organization — a row's own UUID reached
  through a composite foreign key. Anything keyed on a *guessable* value (a
  Property Key, an appointment reference, a `wamid`, an idempotency key, an event
  key) or on nothing at all must filter, because that is the query that answers
  with another brokerage's row;
- an inbound identifier — WhatsApp number, Telegram bot, public hostname —
  resolves through `OrganizationRouting`. An unbound one is a refusal. Never
  default to "the only Organization";
- a credential is never inherited. `IntegrationCredentials.resolve` answers for
  one Organization or refuses. The process environment belongs to the single
  founding Organization named by `PLATFORM_BOOTSTRAP_ORGANIZATION_SLUG`;
- commercial, catalog, conversation and analytics work takes an `Actor`.
  Provisioning, configuration, entitlements and the data lifecycle take a
  `PlatformOperator`. Do not add a surface that accepts both;
- there is no superadmin, and adding one is an ADR rather than a patch. Reading a
  customer's records means a temporary, explained, expiring support grant;
- a configuration document never contains a credential. Store a reference.

See `docs/architecture/architecture.md` and ADR-0033 through ADR-0055 for the
reasoning and the operating limits, and `docs/run/deployment.md` for the three
Deployment Environments and which provider identity belongs to which.

## Implementation Style

- Keep the MVP simple and operational.
- Prefer deterministic backend authority beneath natural-language interaction.
- Do not replace Hermes with a rigid intent classifier or dialogue tree.
- Keep the standalone Hermes plugin thin. It exposes typed operations to Hermes
  and calls the Product API; it must not import the Product database layer or
  own business rules.
- Use PostgreSQL as the product system of record.
- Keep `.env` for secrets only. Non-secret behavior belongs in code defaults,
  docs, or explicit configuration.
- Add tests around behavior contracts and recovery paths, not fragile snapshots.

## Local Development

The canonical runtime is Docker Compose: PostgreSQL, Product, and Hermes each
run in their own container. Do not add a second host/virtualenv startup path.

```bash
cp .env.example .env  # once; fill the required secrets
docker compose up --build
docker compose exec product pytest
```

Only Product port 8080 is published. Product and Hermes share a private network
namespace because Hermes's session-token protocol is intentionally loopback-only.
The Hermes image pins and fetches the reviewed upstream source commit itself;
no sibling checkout is required to run Maia.

## Git Hygiene

Default public branch: `main`.

Recommended private branch prefix: `private/`.
Recommended implementation branch prefix: `codex/` or `feature/`.

Before committing, check:

```bash
git status --short
git diff --stat
git diff -- . ':!PROJECT_MEMORY.md'
```

Never add ignored runtime state with force unless the user explicitly asks and
the file is verified public-safe.
