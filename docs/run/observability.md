# Operational telemetry

Maia keeps three deliberately separate records:

- Inbox, Outbox and Audit Events are authorized business records and may contain
  customer data according to their own policies.
- The Operational Trace Ledger is a 30-day, redacted technical timeline for
  diagnosing one interaction.
- Metrics are aggregate counters and duration buckets; they contain no customer
  or trace identifiers.

## Configure Sandbox

Generate a dedicated secret locally and put it only in `.env`:

```bash
openssl rand -hex 32
```

```dotenv
TELEMETRY_HMAC_KEY=<generated value>
TELEMETRY_RETENTION_DAYS=30
```

`TELEMETRY_HMAC_KEY` produces the organization-scoped Customer Trace Handle. It
is not interchangeable with a provider credential or the plugin credential.
Without it, `/health` reports operational telemetry as degraded and no customer
handle is written.

Apply the migration and recreate the Product service after a safe test-window
decision:

```bash
docker compose up -d --build product
```

## Investigate a report

The Platform Operator reads only redacted technical evidence:

```bash
curl \
  -H "Authorization: Bearer $PLATFORM_OPERATOR_TOKEN" \
  -H "X-Platform-Operator: Guillermo" \
  'http://127.0.0.1:8080/platform/telemetry/traces?channel=WhatsApp'
```

Use the returned `interaction_id` with:

```bash
curl \
  -H "Authorization: Bearer $PLATFORM_OPERATOR_TOKEN" \
  -H "X-Platform-Operator: Guillermo" \
  'http://127.0.0.1:8080/platform/telemetry/traces/<interaction-id>'
```

The trace index may filter by time, channel, stage, outcome, organization or a
Customer Trace Handle. It deliberately cannot search phone numbers, names,
message text, URLs or provider payloads.

## Retention

Every telemetry event is created with `expires_at = occurred_at + retention`.
The in-process maintenance loop runs daily and selects at most 500 expired rows
under a lock, physically deletes that batch, commits, and leaves any remaining
rows for the next pass. It never changes Inbox, Outbox, Audit Events, Contacts
or commercial history.

The trace ledger is non-authoritative. If its write or purge fails, structured
logs and `/health` show telemetry degradation, but customer work continues.
