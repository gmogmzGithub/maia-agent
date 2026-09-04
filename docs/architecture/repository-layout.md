# Repository Layout

Maia is organized around runtime responsibility and product authority, not
generic buckets such as `services`, `controllers`, or `utils`.

## Top Level

| Path | Purpose |
|---|---|
| `src/realestate/` | Maia Product and public-site source code. |
| `plugin/realestate_hermes_plugin/` | Standalone Hermes plugin. It calls Product APIs and owns no Product database logic. |
| `tests/` | Automated tests grouped by the layer or behavior they protect. |
| `migrations/` | Alembic migrations for PostgreSQL and supporting schemas. |
| `docker/` | Product and Hermes container definitions plus the Hermes entrypoint. |
| `docs/` | Public-safe architecture, runbooks, decisions, research, and operating notes. |
| `roles/` | Hermes role/profile material that is safe to keep in source control. |
| `bootstrap/` | Public-safe Sandbox import inputs; never a runtime catalog or storage location. |
| `src/properties/` | Public-safe accepted property catalog fixtures for local operation. |
| `secrets/` | Local-only secret mount point. Only `.gitkeep` belongs in Git. |

`output/`, `tmp/`, caches, virtual environments, build output, coverage files,
and packaged metadata are generated artifacts. They should stay out of Git.

## Source Package

The source package mirrors Maia's runtime split:

| Package | Role |
|---|---|
| `realestate.api` | FastAPI routers and server-rendered operator surfaces. This is the closest equivalent to controllers. |
| `realestate.domain` | Business authority: policy, commands, records, invariants, and PostgreSQL-backed product workflows. |
| `realestate.db` | SQLAlchemy engine and ORM model definitions. This is the persistence adapter. |
| `realestate.worker` | Background workers and polling loops. |
| `realestate.channels` | External adapters for WhatsApp, Facebook Messenger, Instagram, Telegram, and Google Calendar. |
| `realestate.hermes` | Product-side Hermes runtime client and session binding. |
| `realestate.infrastructure` | Provider-specific implementations of domain ports, including S3-compatible Listing Media storage. |
| `realestate.site` | Public-site SSR app, templates, static assets, and Product gateway. This is the GUI/web frontend layer. |

When adding code, first ask which responsibility owns the decision. Do not place
business rules in routers, channel clients, workers, or templates just because
they are the current caller. Put rules in `realestate.domain` and let adapters
call them.

## Domain Package

`realestate.domain` is intentionally split by product area:

- `commercial/` owns Contacts, Opportunities, assignment, next actions,
  conversation handling, team administration, and CRM read models.
- `platform/` owns Organization provisioning, routing, credentials,
  entitlements, support grants, lifecycle, imports, and usage.
- `catalog/` owns authoritative Product listings, media records, offers, and
  presentation policy.
- `public/` owns public-site contracts, discovery, saved collections, handoff,
  measurement, and publication rules.
- `external_inventory/` owns the read-only external inventory port and
  EasyBroker adapter-facing decisions.
- `engagement/` owns consent, audiences, reactivation candidates, provider
  template observations, and campaign lifecycle.
- `analytics/` owns event taxonomy, pseudonymization, projection, traffic
  classification, and measurement reporting.
- `sponsorship/` owns paid visibility eligibility, pricing, capacity, delivery,
  reporting, and buyer-sharing contracts.
- `scheduling/` owns advisor calendars, appointment policy, reminders, and
  appointment handoff.

Small single-file modules directly under `realestate.domain` are cross-cutting
Product concepts or older seams that have not earned a subpackage yet.

## Test Layout

| Path | Confidence provided |
|---|---|
| `tests/api/` | Router behavior, operator pages, plugin tools, upload/webhook/public-site surfaces. |
| `tests/domain/` | Business policy, records, invariants, authorization, product workflows, and privacy rules. |
| `tests/infrastructure/` | Database engine, channel adapters, Hermes client/session integration, payload parsing, formatting, and persistence. |
| `tests/integration/` | Vertical scenarios and app lifecycle tests. |
| `tests/migrations/` | Alembic revision behavior and ORM/schema compatibility. |
| `tests/workers/` | Background loop and worker orchestration. |
| `tests/fixtures/` | Shared fixture builders, fakes, and test data helpers. |

Prefer adding a new test next to the behavior it protects. If a test needs a
helper from another product area, promote that helper to `tests/fixtures/`
instead of importing from another test module.
