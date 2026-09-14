---
status: accepted
---

# Separate redacted operational telemetry from customer records

Maia will carry a production Observability Contract from Sandbox: every accepted
customer interaction must be reconstructable through a correlation identifier
across ingress, routing, Hermes and typed tools, durable outcome, provider side
effect and timings. Operational telemetry contains only opaque or pseudonymous
identifiers, outcomes, durations and classified errors; it never copies message
or document content, identities, raw provider payloads, credentials, headers or
URLs/query strings. Inbox, Outbox and Audit Events remain the separately
authorized records for customer content and business history, not a substitute
for diagnostic logs.

## Considered options

Using raw application logs as incident history was rejected because they leak
customer data and disappear under rotation. Treating the business database as
the general log stream was rejected because it mixes authorization-sensitive
records with high-volume technical detail and makes ordinary diagnosis depend on
customer-record access. Remote telemetry and paging are deferred: the Platform
Operator is the only telemetry reader during Sandbox, while the event contract
is kept portable to a future production destination.

## Consequences

An Interaction Trace has one Interaction ID for the accepted customer event and
separate attempt identifiers for each delivery, retry, processing step and
provider side effect. The Operational Trace Ledger retains only redacted
lifecycle milestones and failures for 30 days by default, configurable by
deployment environment. Its writes are non-authoritative: a telemetry failure
must be visible through structured logs and health/metrics, but must never
reject, roll back or hide a valid customer outcome.

Every trace stage records a bounded Operational Outcome: succeeded, refused as
designed, deferred for retry, retryable failure, terminal failure or unknown
external outcome. A protected Trace Lookup presents this redacted timeline to
the Platform Operator; it is not a customer-record search surface and does not
authorize content access.

Trace Lookup starts from a newest-first Trace Index filtered only by safe
technical fields. Maia also exposes protected, standards-compatible Operational
Metrics using only bounded labels for stage, channel, outcome and error class;
identifiers and customer-derived values are forbidden metric labels.

Telemetry Degradation is exposed as its own health component and must not make
an otherwise ready customer-facing Product unavailable. Product resolves each
typed call from the Hermes-issued session ID against its own durable session
binding. It derives the Interaction Trace from that trusted binding and never
accepts a model- or plugin-supplied interaction ID. This context grants neither
caller authority nor permission to access customer records.

Every structured log and ledger milestone uses a versioned Telemetry Event
Envelope: timestamp, event name, stage, outcome, severity, Interaction ID,
attempt ID, Organization ID, completed duration and classified error code where
applicable. Its fields are redacted by construction; the same identifiers never
become metric labels.

Each relevant trace also carries a Customer Trace Handle: a stable, secret-
derived pseudonym of the Organization-scoped channel identity. It supports
technical correlation for one customer without placing a phone number, name or
cross-Organization identifier in operational telemetry.

The ledger records every meaningful lifecycle boundary—ingress, routing,
deduplication, worker claim or retry, Hermes turn, typed tool, business outcome
and provider side effect—but not arbitrary debug chatter. Failures, safe
refusals and lifecycle milestones are never sampled. Error evidence is
allowlisted: code, type, retryability and stable fingerprint only. Exception
messages and provider response bodies are absent by design, with a generic
redaction filter as a defence-in-depth backstop.
