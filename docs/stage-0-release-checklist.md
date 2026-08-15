# Stage 0 Release Checklist

This is the acceptance checklist for Maia's local Stage 0/Stage 0B product
prototype. It is deliberately narrower than production readiness: no cloud
deployment, multi-tenant isolation, CRM integration, paid acquisition, or
legal/privacy approval is required here.

## Product acceptance

| Area | Required evidence |
| --- | --- |
| Property administration | A submission accepted from `/admin/properties/new` writes the public-safe catalog copy, an immutable PostgreSQL document version, and a first `Active` Property. A replacement preserves the current status. |
| Customer conversation | A live Sales evaluation proves current-document lookup, grounded answers, tool use, clarification, and unavailable-property safety. |
| Administrative conversation | A live Admin evaluation proves status mutation, trusted audit identity, reactivation, inventory listing, and no mutation for ambiguous instructions or missing inactive reason. |
| Appointment path | Credential-free tests prove availability, booking policy, Calendar conflict handling, ambiguous outcomes, deterministic notices, and Telegram notification state. A real provider rehearsal is still required before using a real lead. |
| Follow-up path | The Product worker owns the WhatsApp-only cadence `(1, 5, 7, 14, 18, 22, 26, 28)`, opt-out, idempotency, and Outbox delivery. It never asks Hermes to decide when to follow up. |
| Recovery | Tests cover Inbox lease recovery, Outbox retry and `DeliveryUnknown`, Calendar `NeedsReview`, inactive-property appointment review, and bounded administrative resolution. |
| Runtime | Product, Hermes, PostgreSQL, WhatsApp, Telegram, Calendar, and the Product background loop report healthy; Product can reach the loopback Hermes endpoint. |

## Required local gate

With the Compose runtime running:

```bash
docker compose exec -T product ruff check src plugin tests migrations
docker compose exec -T product pytest -m 'not live_provider' --strict-markers --cov
```

The command must have no skipped tests. The live Hermes capability tests are
skipped when Product cannot reach port `9119`; that is a runtime failure, not a
successful token-free result.

## Live model evaluation

Run these intentionally because they call the configured model provider and
mutate the local development inventory used by the fixtures:

```bash
docker compose exec -T -e RUN_CONVERSATION_TESTS=1 product \
  pytest tests/test_sales_conversation.py tests/test_admin_conversation.py \
  --strict-markers
```

The Admin suite treats `desactiva Casa Roble` without a reason as an
ambiguity. The model must ask for a reason and must not mutate the Property.
Explicit facts such as `Casa Roble se vendió` use the corresponding inactive
reason and execute immediately.

## Backup and restore rehearsal

The following creates a temporary database inside the PostgreSQL container,
restores the current database into it, verifies the schema and core records,
and removes only that temporary database. It does not touch the running
database or Compose volumes:

```bash
docker compose exec -T db sh -lc '
set -eu
dump_path=/tmp/maia-stage0-rehearsal.sql
restore_db=maia_stage0_restore_check
pg_dump -U realestate -d realestate --no-owner --no-privileges > "$dump_path"
dropdb -U realestate --if-exists "$restore_db" >/dev/null
createdb -U realestate "$restore_db"
psql -U realestate -d "$restore_db" -f "$dump_path" >/dev/null
psql -U realestate -d "$restore_db" -Atc \
  "SELECT (SELECT count(*) FROM properties), (SELECT count(*) FROM audit_events), (SELECT version_num FROM alembic_version)"
dropdb -U realestate "$restore_db" >/dev/null
rm -f "$dump_path"
'
```

For a real pilot, move this to scheduled encrypted backups with a documented
restore owner, recovery point objective, recovery time objective, and provider
secrets recovery procedure. Those are intentionally outside the local Stage 0
prototype.

## Failure rehearsal

The local recovery contract is considered exercised when the following tests
remain green and one operator can explain the manual outcome of each case:

- restart Product or Hermes while Inbox work is pending;
- let an Inbox lease expire and verify it is reclaimed rather than duplicated;
- return an ambiguous Meta delivery result and verify `DeliveryUnknown` is not
  automatically replayed;
- return an ambiguous Calendar write and verify `NeedsReview`, never a false
  confirmation;
- deactivate a Property with a future confirmed visit and resolve the resulting
  administrative review without automatically cancelling the visit;
- opt a Lead out and verify no later follow-up Outbox row is created.

## Retention decision for Stage 0

Stage 0 is a local prototype and must use synthetic or deliberately approved
test data only. PostgreSQL state, audit history, accepted Property artifacts,
and the catalog projection remain until an operator explicitly backs up and
resets the local environment. Maia does not silently delete local evidence.

Before a real customer pilot, define retention periods and deletion authority
for lead messages, provider payloads, audit records, appointment evidence, and
property documents as a separate privacy/business decision.

## External final check

The local Product port is not publicly reachable by Meta. Before a real
WhatsApp rehearsal, start an HTTPS tunnel to port 8080 and set the Meta app's
WhatsApp webhook callback to the tunnel URL plus `/webhooks/whatsapp`. Verify
the callback challenge returns HTTP 200 before sending a message. A temporary
tunnel URL changes when the tunnel restarts; a stale URL produces no Inbox row
and therefore no reply, even when Product, Hermes, and the Meta token are
healthy.

Provider health proves reachability and credentials, not message delivery. The
final manual check must use a consenting test recipient and verify one real
WhatsApp conversation, one real outbound reply, one real Calendar booking or
conflict outcome, and the corresponding Telegram notice. Do not use a real
customer until that rehearsal and the data-retention decision are complete.
