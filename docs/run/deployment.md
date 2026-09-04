# Deployment

Maia runs in exactly three Deployment Environments: **Sandbox**, **Pilot**,
**Public** (CONTEXT.md, and ADR-0060 for why). This document is the operational
half of that decision.

It is a plan, not a verified runbook. `PROJECT_MEMORY.md` withheld deployment
documentation until a live target existed; this is written as that target is being
stood up, so every section is expected to be corrected from what actually
happened. Correct it in place rather than adding a second account of the truth.

For the local runtime itself — starting it, proving it is up, the required test
gate — see `docs/run/everything-locally.md`. For the runtime split this deploys,
see `docs/architecture/architecture.md`.

## What each environment is for

| | Sandbox | Pilot | Public |
|---|---|---|---|
| Purpose | Guillermo and Santiago build and review | small invited audience, Meta ads on, does Maia convert? | open to the market |
| Contacts | synthetic only | real | real |
| Properties | a few real documents | a few real listings | the full authorized catalog |
| Reachable by | the two of us | ad clicks and invited people | anyone |
| Discoverable | never | never | yes, and only here |
| Host | always-on Mac mini | one AWS EC2 host | AWS, defined at that phase |

## Identity matrix

Nothing in a row below is shared between two columns. This is the rule that
prevents silent misrouting (ADR-0060), and Channel Binding enforces the customer
channels, Telegram and hostname half of it by refusing an unbound identifier
rather than resolving it to a default.

| | Sandbox | Pilot | Public |
|---|---|---|---|
| Hostname | `sandbox.elmenlabs.com` | `piloto.elmenlabs.com` | Brokerage Brand domain (TBD) |
| `SITE_PUBLIC_ORIGIN` | the hostname above | the hostname above | the hostname above |
| WhatsApp | Meta developer test number | dedicated business number | same as Pilot |
| Facebook Messenger | dedicated test Page | dedicated business Page | same as Pilot |
| Instagram | test professional account | dedicated professional account | same as Pilot |
| Meta app | dev app | production app | production app |
| Telegram bot | its own bot | its own bot | its own bot |
| Model key | its own Anthropic key | its own Anthropic key | its own Anthropic key |
| Calendars | test calendars | the Advisors' real calendars | real |
| PostgreSQL | container on the Mac mini | container on the EC2 host | RDS with PITR |
| Listing Media bytes | private MinIO volume | private AWS S3 bucket | private AWS S3 bucket + CloudFront |
| Discovery | withheld | withheld | published |
| Operator surfaces | Cloudflare Access + credential | Cloudflare Access + credential | to be decided |

`SITE_PUBLIC_ORIGIN` must equal the environment's own hostname. It is what
absolute URLs, canonical links, structured data and `robots.txt` are built from,
so a stale value publishes another environment's links.

**Maia's WhatsApp number is dedicated and is not on anybody's phone.**
Registering a number to the Cloud API removes it from the WhatsApp consumer app.
A human who wants to answer a Contact personally does so in `/crm` by taking the
Conversation (ADR-0029); the number only needs a SIM once, to receive the
registration code.

## DNS

`elmenlabs.com` is a personal domain and the Platform Vendor's home. Maia creates
and owns **only** the `sandbox.` and `piloto.` records. The apex, `www`, and any
future MX belong to the personal landing page and to mail; no Maia change touches
them, so a mistake here cannot take down the page a recruiter is reading or the
founder's email.

| Record | Points at |
|---|---|
| `elmenlabs.com`, `www` | the personal landing page (Cloudflare Pages, static Next.js export) |
| `sandbox.elmenlabs.com` | Cloudflare Tunnel → Mac mini |
| `piloto.elmenlabs.com` | Cloudflare Tunnel → EC2 |

If the brokerage becomes a separate legal entity, its DNS is currently inside a
personal Cloudflare account. Acceptable for Sandbox and Pilot; untangle it before
Public.

## Sandbox

Runs the unmodified `docker compose` topology on the Mac mini. No purchased
hosting: a **named** Cloudflare Tunnel publishes port 8080 over TLS. A named
tunnel matters — a quick-tunnel URL changes on restart, and a stale webhook URL
produces no Inbox row and therefore no reply while Product, Hermes and every
provider credential go on reporting healthy.

Cloudflare Access sits in front of `/crm`, `/admin` and `/platform` with email
one-time-pin for the two of us. It must **not** cover `/`,
`/webhooks/whatsapp`, `/webhooks/messenger`, or `/webhooks/instagram`: Meta
cannot complete a webhook handshake through Access, and each webhook
authenticates the raw body with its configured app-secret signature.

Listing Media already uses the cloud-shaped storage boundary: Product writes
checksummed objects to two private MinIO buckets through the AWS S3 client, while
PostgreSQL owns authority and provenance. The Site has no storage credential.
MinIO's named Docker volume is operational storage; `bootstrap/sandbox/` is only
the explicit source for a fresh synthetic import and is never served directly.

Because the Mac mini is expected to stay up unattended:

- `restart: unless-stopped` on every long-lived Compose service;
- `pmset` set never to sleep, and to restart after a power failure;
- automatic login, with Docker set to start at login;
- `cloudflared` installed as a system service, not left in a terminal;
- an external uptime check on `/live` alerting both of us — `/live` is a bare
  liveness probe, which is why it is the one that stays open;
- a nightly `pg_dump` plus an object-storage backup written off the Mac mini.
  The Contacts are synthetic, but the property documents and catalog work are
  real effort and that disk must not be their only copy.

Deploys are by hand: `git pull && docker compose up -d --build`. Keep the test
dependencies in the Sandbox image —
`docker compose exec product pytest` is the fastest diagnostic available.

## Pilot

One **EC2 `t4g.small`** (2 vCPU ARM, 2 GB) with 20 GB gp3 in **`us-east-1`**,
roughly $12–15/month. ARM matches the Apple-silicon Mac mini, so the same image
architecture runs in both environments. Add 4 GB of swap.

Region: not `mx-central-1` yet. Perceived latency is dominated by the model
round trip, and Mexican data-protection law requires a privacy notice and
safeguards for transfers, not in-country storage. Revisit at Public as a comfort
and positioning argument.

Edge: **Cloudflare Tunnel again**, not an ALB. One edge model across two
environments, no inbound port open on a host holding real personal data, and no
$18/month load balancer in front of a single container. The ALB, CloudFront and
WAF belong to Public, where there is traffic to justify them and Terraform to
describe them.

Images are built in **GitHub Actions** for `linux/arm64` and pushed to **GHCR**;
the box pulls and restarts. Do not build on the box — 2 GB of RAM building Hermes
invites an OOM in the middle of a deploy. Pilot pulls a **production image
target** without `.[dev]` and without `tests/`.

Data: Pilot starts **empty** and gets a fresh Organization through a
Provisioning Run (ADR-0055), which is also the first time that resumable,
reversible sequence is exercised against something real. Real
property documents are uploaded deliberately. **No Sandbox dump is ever restored
into Pilot** — after that nobody could say which Opportunities had been real.
Listing Media uses a private AWS S3 bucket through the same Adapter exercised in
Sandbox; only endpoint and credential configuration changes.

Backups, meeting the Pilot recovery objective of RPO 24h / RTO 2h: nightly
encrypted `pg_dump` to object storage with 30-day retention, plus a daily EBS
snapshot, plus **one rehearsed restore before the first ad runs** — restoring
the dump into a scratch database and checking the row counts and the Alembic
revision, which is cheap to do and the only thing that proves the dump is a
backup rather than a file. Pilot additionally needs what a local rehearsal never
did: a named restore owner.

AWS account hygiene, done once: MFA on root, root never used again, an admin
identity for daily work, a billing alarm at the monthly ceiling, and a separate
spend limit on the model provider.

## Public (sketch, not yet decided in detail)

The shape this is aimed at, so Pilot choices do not block it:

- **Terraform** in `infra/`, and **GitHub Actions deploying by OIDC** with no
  long-lived AWS keys;
- **ECR** images pinned by digest;
- **one ECS Fargate task holding product, hermes and site together** — `awsvpc`
  gives them the shared loopback that Hermes's session-token protocol requires
  (`network_mode: service:product` today). They cannot become separate services;
- **RDS PostgreSQL with point-in-time recovery**;
- **Secrets Manager**, resolved through the existing Secret Reference indirection
  (ADR-0052) — Product already stores the name of the place a value lives, which
  is exactly a secret ARN;
- **S3 for property documents, Listing Media and Organization exports**. The
  Listing Media port and Adapter already exist; the other artifact types still
  need migration. EFS would avoid those remaining code changes, but would also
  preserve host-filesystem coupling;
- ALB + ACM, CloudFront over listing media, WAF on the operator paths,
  CloudWatch alarms on the health endpoint, and **no NAT Gateway** — it alone
  would cost more than the whole Pilot host.

Public is also where the public site moves to the Brokerage Brand's domain and
becomes discoverable for the first time.

## Single instance, deliberately

Product runs as exactly one instance in every environment up to Public. The
background workers are in-process, Property Documents and export artifacts are
on local volumes, and
`alembic upgrade head` runs at container start. Two instances would race the
migration and duplicate paced work — broker digests, reminders, upkeep passes —
and `PROJECT_MEMORY.md` already notes an internal alert can double-deliver. The
cost is a deploy interruption of under a minute, absorbed by Meta's webhook
retries. Splitting web from worker and moving the remaining artifacts to S3 is
Public-phase work, not a fix for an accident.

## Promotion gates

### Sandbox → Pilot

External, start early because they are pure waiting:

- Meta business verification, WABA, approved display name, and the dedicated
  number registered to the Cloud API;
- an *aviso de privacidad* published on the public site, with named retention
  periods for lead messages, provider payloads, conversation content, appointment
  evidence and property documents, and a named deletion authority. The Stage 0
  checklist deferred this explicitly; Pilot is when it comes due;
- scheduled encrypted backups with the stated RPO/RTO, a named restore owner, and
  one rehearsed restore.

Code, all small and all required by the move to a public origin:

- a site-wide discovery switch, defaulting to **withheld**: `X-Robots-Tag:
  noindex` on every page, `robots.txt` returning `Disallow: /`, and `sitemap.xml`
  withheld. Per-page `noindex` exists already; the environment-level rule does
  not;
- `/health` behind the same authentication as `/crm`. It currently enumerates
  six dependencies, including private object storage, to anonymous callers,
  which tells a stranger which provider credentials exist and how they are
  failing; `/live` stays open;
- uvicorn `--proxy-headers` with trusted forwarding, `TrustedHostMiddleware`
  pinned to the environment hostname, and HSTS. Without the first, the app sees
  the tunnel as the client and believes every request is plain HTTP — and the
  public site's cookies are `secure=True`;
- `restart: unless-stopped` on every service;
- a production image target without dev dependencies or tests.

### Pilot → Public

- the Brokerage Brand's domain chosen and bought, and the cutover planned with a
  lowered DNS TTL and a rollback;
- discovery enabled for the first time, on that domain only;
- RDS with PITR, and object-storage Adapters for the remaining artifact types;
- the measured question Pilot existed to answer, answered.

## Deliberately open

- The Brokerage Brand's domain, deferred until the project and agent names
  settle. Withheld discovery on Pilot is what makes deferring free.
- Whether Public's operator surfaces keep HTTP Basic. The platform-wide login
  namespace is already a recorded open question (`PROJECT_MEMORY.md`).
- Analytics retention (ADR-0044), unchanged by any of this.
