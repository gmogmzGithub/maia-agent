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
3. runs Ruff and every test except those marked `live_provider`;
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

## Run the required gate locally

With the Compose runtime running:

```bash
docker compose up --build -d
docker compose exec product ruff check src plugin tests migrations
docker compose exec product mypy
docker compose exec product pytest -m 'not live_provider' --strict-markers --cov
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

## Where each kind of confidence comes from

| Layer | Credential-free | What it protects |
|---|---:|---|
| Unit and domain tests | Yes | Policy, parsing, retries, ambiguity, copy, and authorization |
| Database/API/worker integration tests | Yes | PostgreSQL contracts, Inbox/Outbox, plugin calls, sessions, and recovery |
| Commercial domain tests | Yes | Contact resolution, stages, qualification, assignment races, Next Actions, retention |
| Migration tests | Yes | The commercial and catalog revisions on an empty and a legacy database, upgrade and downgrade |
| Operator surface tests | Yes | Mexican Spanish, accessibility, empty states, refusals, and that a CRM reply goes out only through the outbound eligibility gate |
| Vertical system scenario | Yes | WhatsApp inquiry through booking and Broker notification, and Inbox to Next Action |
| Live model evaluation | No | Hermes/model tool choice, grounding, and conversational quality |
| Manual channel rehearsal | No | Real Meta, Google Calendar, and Telegram configuration and delivery |
