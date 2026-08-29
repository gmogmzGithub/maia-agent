# Testing Maia without provider credentials

Maia's required test gate does not need a Meta token, an Anthropic token, a
Telegram token, or Google credentials. External transports are replaced at
their boundaries while Maia's database, APIs, workers, policy, and durable
state transitions remain real.

## The required gate

GitHub Actions runs `.github/workflows/tests.yml` for every pull request and
every push to `main`. The job:

1. creates an environment in which every provider credential is blank;
2. builds and starts the complete Product, Hermes, and PostgreSQL Compose
   topology, waiting on the healthchecks that prove Product can reach the
   loopback-only Hermes endpoint;
3. runs Ruff and every test except those marked `live_provider` or
   `live_external_inventory`;
4. fails below the coverage floor set in `pyproject.toml`;
5. fails if any selected test is skipped, so a missing service cannot silently
   turn a required integration scenario green;
6. retains JUnit and coverage XML reports as workflow artifacts.

The vertical scenario in `tests/test_token_free_system_flow.py` covers the
customer path discussed during the first live rehearsal:

```text
signed WhatsApp webhook
  -> PostgreSQL Inbox
  -> Sales worker and durable Hermes session binding
  -> authenticated Product tools
  -> property document and availability policy
  -> fake Calendar event
  -> deterministic WhatsApp Outbox confirmation
  -> signed delivery-status callback
  -> fake Telegram Broker notice
```

The scenario scripts only the model's judgment and fakes only the remote
provider transports. It therefore verifies Maia's real orchestration and
authority boundaries without pretending that a language-model answer is
deterministic.

`tests/test_stage_three_e2e.py` does the same for the human-operation paths, with
the same discipline: a signed webhook in, the real Inbox and Lead worker, the real
authenticated product tools, the real CRM an Advisor uses, and the internal alert
channel. Its four scenarios are the branches the stage promises —

```text
webhook -> Maia answers -> Maia books -> Advisor is the owner
        -> post-appointment commercial question -> Advisor, not Maia
        -> Advisor answers on the official channel -> records the outcome

webhook -> "quiero hablar con una persona" -> Maia stops
        -> approved acknowledgement to the Contact
        -> immediate internal alert -> 15-minute escalation, once
        -> a human takes it, then returns it to Maia explicitly

webhook -> confirmed visit -> Maia reschedules it atomically
        (new slot secured before the old one is released)

Advisor without an authoritative calendar -> no times offered, honestly
```

— and no provider token is involved in any of them.

Stage 8 adds two adversarial suites rather than more happy paths.
`tests/test_sponsored_surfaces.py` asserts that the organic result order is
byte-identical with and without an Active campaign over one of the results, under
every sort, and then asserts it *structurally*: the module that ranks public
results contains no reference to sponsorship at all, so no future change can make
payment influence relevance by accident.

`tests/test_sponsorship_privacy.py` goes looking for leaks instead of confirming
one. It puts a real phone number, a Contact id, a lead id, a criterion in the
Contact's own words and a Saved Collection token into the database, then searches
the buyer report object, the rendered page lines and the PDF bytes for every one
of them.

## Run the required gate locally

With the Compose runtime running:

```bash
docker compose up --build -d
docker compose exec product ruff check src plugin tests migrations
docker compose exec product mypy
docker compose exec product pytest \
  -m 'not live_provider and not live_external_inventory' --strict-markers --cov
```

The measured packages, the report format, the coverage floor, and the
type-checked paths all come from `pyproject.toml`, so this is the same gate CI
applies.

`mypy` runs in `--strict` mode and is a required gate rather than advice. It is
what makes a union return such as `OutboundMessaging.request`'s
`Queued | Denied` an enforced contract: reading `outbox_id` off a refusal, or
`reason` off an approval, fails here instead of shipping (ADR-0045).

The tests selected by that command do not call Meta, Anthropic, Google, or
Telegram. CI additionally blanks those credentials and disables the background
worker, making accidental provider traffic impossible there.

## Optional live-provider evaluation

Model behavior is evaluated separately because it is slower, costs money, and
is nondeterministic. Run it intentionally when a model, prompt, role guide, or
tool-description change warrants a live evaluation:

```bash
docker compose exec -e RUN_CONVERSATION_TESTS=1 product \
  pytest -m live_provider --strict-markers
```

That command needs a working Hermes runtime and its configured model-provider
credential. It does not replace the required token-free gate. A real WhatsApp,
Calendar, and Telegram rehearsal remains a manual release check because it
creates provider-side effects.

EasyBroker staging is separate and read-only. It is never required by public CI:

```bash
docker compose exec \
  -e RUN_EASYBROKER_LIVE_TESTS=1 \
  -e EASYBROKER_STAGING_API_KEY=... \
  product pytest -m live_external_inventory --strict-markers
```

Use only a separate staging key. This proves transport compatibility, not API MLS
entitlement, collaborator authority, retention permission, or production access.

## Where each kind of confidence comes from

| Layer | Credential-free | What it protects |
|---|---:|---|
| Unit and domain tests | Yes | Policy, parsing, retries, ambiguity, copy, and authorization |
| Database/API/worker integration tests | Yes | PostgreSQL contracts, Inbox/Outbox, plugin calls, sessions, and recovery |
| Commercial domain tests | Yes | Contact resolution, stages, qualification, assignment races, Next Actions, retention |
| Migration tests | Yes | The commercial, catalog, analytics and managed-platform revisions on an empty and a legacy database, upgrade and downgrade, including the separate `analytics` schema, its seeded measurement definitions, and that the ORM metadata matches the migrated schema exactly |
| Operator surface tests | Yes | Mexican Spanish, accessibility, empty states, refusals, and that a CRM reply goes out only through the outbound eligibility gate |
| Vertical system scenario | Yes | WhatsApp inquiry through booking and Broker notification, and Inbox to Next Action |
| Live model evaluation | No | Hermes/model tool choice, grounding, and conversational quality |
| EasyBroker staging smoke test | No | Opt-in read-only provider transport compatibility only |
| Stage 7 engagement tests | Yes | Explainable matches, explicit audiences, consent/template lifecycle, caps, stops and PII-safe results |
| Stage 8 measurement tests | Yes | Event idempotency, emission order, replay from zero, restart mid-batch, schema and definition versions, exact visibility and exploration borders, invalid-traffic classification and reporting, late events, materialized-view refresh, and `Sin registrar` kept distinct from zero |
| Stage 8 sponsorship tests | Yes | Identical organic ordering with and without payment, the visible and accessible `Patrocinada` label, session caps, equitable rotation, capacity that cannot be oversold, quote expiry and preserved catalog version, discounts requiring a reason, comparables and sample size, 7/90-day attribution, non-causal language, and no PII in any buyer view, link or PDF |
| Stage 9 isolation matrix | Yes | Every table classified as one Organization's data or platform-wide with a reason, a NULL scope column in none of them, guessed identifiers and short readable references refused across the boundary, the same Property Key / Outbox key / delivery id usable by both Organizations, two live Organizations' inbound numbers routing only to their own records, an unbound number refused rather than defaulted, no credential inherited, no credential or salt in any row, audit event or export, and the workers attributing each row they touch to its own Organization |
| Stage 9 platform operations | Yes | Provisioning that resumes from a failed step and leaves the Organization inoperable until the last one, rollback that keeps configuration and entitlement history, a login another Organization holds refused by name, versioned configuration idempotent on the document and refusing a nested credential key, rotation that keeps both references and proves the change, an entitlement change explainable before and after, a seat ceiling with its numbers in the sentence, support access expiring at login resolution rather than by the sweep, dry-run and apply agreeing per record, rollback by stored identifier, an export naming every withheld column, and a deletion refused outright by a live retention hold |
| Stage 9 simultaneous rehearsal | Yes | Two synthetic Organizations accept inbound messages concurrently, preserve distinct Product truth, queue reactive replies through the eligibility gate, and deliver each reply through the Organization's own Meta token and phone binding |
| Stage 9 bounded local capacity | Yes | 100 synthetic inquiries, split evenly across two Organizations with concurrency ten, must persist in the correct scopes within a broad 30-second regression guard; this is explicitly not a production throughput promise |
| Stage 10 Journey and market intelligence | Yes | Template approval before use, Journey start without a Won transition, human-only milestone evidence, minimum completed-sale facts, Organization-scoped operational records, privacy-bounded shared projection, direct-SQL revisions and re-projection, analyst-only access, duplicate resolution counting once, individual comparables from the first sale, and aggregate withholding below five records |
| Manual channel rehearsal | No | Real Meta, Google Calendar, and Telegram configuration and delivery |
| Manual browser rehearsal | No | The visibility observer, gallery-depth reporting, and the rendered contrast of the paid label |
