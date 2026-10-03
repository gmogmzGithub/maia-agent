# Run Everything Locally

This is the full local path for Maia: PostgreSQL, Product API, embedded Product
workers, Hermes, public site, CRM/operator surfaces, platform JSON API, plugin
API, migrations, and tests.

Do not use `docker compose down --remove-orphans`; a local Cloudflare tunnel may
be an intentional orphan.

## 1. One-Time Setup

```bash
cd /Users/el-men/workspace/repos/maia-agent
cp -n .env.example .env
```

Fill these first:

```dotenv
HERMES_DASHBOARD_SESSION_TOKEN=<openssl rand -hex 32>
PLUGIN_API_TOKEN=<openssl rand -hex 32>
SITE_PRODUCT_API_TOKEN=<openssl rand -hex 32>
GARAGE_RPC_SECRET=<openssl rand -hex 32>
GARAGE_ADMIN_TOKEN=<openssl rand -hex 32>
GARAGE_METRICS_TOKEN=<openssl rand -hex 32>
OBJECT_STORAGE_ACCESS_KEY_ID=GK<24 hex characters from openssl rand -hex 12>
OBJECT_STORAGE_SECRET_ACCESS_KEY=<openssl rand -hex 32>
DEVELOPER_BASIC_CREDENTIALS_JSON={"<operator-login>":"<local-password>"}
ORGANIZATION_ADMIN_LOGINS=<operator-login>
ORGANIZATION_ADVISOR_LOGINS=<operator-login>
ORGANIZATION_DEFAULT_ADVISOR_LOGIN=<operator-login>
```

The HTTP Basic username must match an Organization member login. Example:
`DEVELOPER_BASIC_CREDENTIALS_JSON={"el-men@maia.com":"..."}` requires
`el-men@maia.com` in `ORGANIZATION_ADMIN_LOGINS` or `ORGANIZATION_ADVISOR_LOGINS`.

Optional real-provider values:

```dotenv
ANTHROPIC_API_KEY=<real Anthropic key>
META_VERIFY_TOKEN=<Meta webhook verify token>
META_APP_SECRET=<Meta app secret>
META_ACCESS_TOKEN=<Meta access token>
META_PHONE_NUMBER_ID=<Meta phone number id>
META_WABA_ID=<WhatsApp Business Account id>
META_FACEBOOK_PAGE_ID=<Facebook Page id>
META_MESSENGER_ACCESS_TOKEN=<Page access token>
META_INSTAGRAM_ACCOUNT_ID=<Instagram professional account id>
META_INSTAGRAM_ACCESS_TOKEN=<Instagram user access token>
TELEGRAM_BOT_TOKEN=<Telegram bot token>
TELEGRAM_ADMIN_IDS=<comma-separated Telegram user ids>
GOOGLE_CALENDAR_CREDENTIALS=/run/secrets/google-calendar.json
GOOGLE_CALENDAR_ID=<calendar id>
EASYBROKER_API_KEY=<EasyBroker key>
PLATFORM_OPERATOR_TOKEN=<local platform operator token>
MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON={"analyst":"<local-password>"}
```

Messenger and Instagram are optional and independent. Leaving their account ids
and tokens empty keeps those channels unbound; it does not affect WhatsApp.
`META_APP_SECRET` is reused only when the products belong to the same Meta app.
For separate apps, set `META_MESSENGER_APP_SECRET` and/or
`META_INSTAGRAM_APP_SECRET`. Instagram Login uses
`META_INSTAGRAM_GRAPH_BASE_URL=https://graph.instagram.com`.

### Connect Facebook Messenger later

1. Create or choose a Facebook Page and a Meta app with Messenger.
2. Give the app `pages_messaging`, generate a Page access token for a person or
   system user allowed to perform the Page's messaging task, and record the Page
   id.
3. Configure the Messenger webhook callback as
   `https://<public-host>/webhooks/messenger`, using `META_VERIFY_TOKEN`, and
   subscribe the Page to the `messages` field.
4. Set `META_FACEBOOK_PAGE_ID`, `META_MESSENGER_ACCESS_TOKEN`, and the applicable
   app secret, then recreate Product. Startup binds the Page and records the
   token's environment-variable name for the founding Organization.

### Connect Instagram later

1. Use an Instagram professional account (Business or Creator) and configure
   Instagram API with Instagram Login in a Meta app.
2. Authorize `instagram_business_basic` and
   `instagram_business_manage_messages`, then record the professional-account id
   and Instagram user access token.
3. Configure the Instagram webhook callback as
   `https://<public-host>/webhooks/instagram`, using `META_VERIFY_TOKEN`, and
   subscribe to `messages`.
4. Set `META_INSTAGRAM_ACCOUNT_ID`, `META_INSTAGRAM_ACCESS_TOKEN`, and the
   applicable app secret, then recreate Product. Do not put a username where the
   numeric professional-account id belongs.

Both callbacks must be public HTTPS paths and must bypass Cloudflare Access.
Product verifies `X-Hub-Signature-256`, resolves the receiving Page/account to
one Brokerage Organization, persists the message, and only then acknowledges
Meta. A message from an unbound id is refused and counted; it is never assigned
to the only Organization.

For a non-founding Organization, first place each token in the deployment's
secret store. Then use the existing `/platform/organizations/{id}/channels` and
`/platform/organizations/{id}/credentials` endpoints to record these exact
enum values:

| Channel | Binding kind | Credential provider |
| --- | --- | --- |
| Facebook Messenger | `FacebookPageId` | `MetaMessenger` |
| Instagram | `InstagramAccountId` | `MetaInstagram` |

The credential endpoint receives only the secret reference name, never the
token value.

If using Google Calendar:

```bash
mkdir -p secrets
# put the service-account JSON here:
# /Users/el-men/workspace/repos/maia-agent/secrets/google-calendar.json
```

## 2. Start Everything

First build:

```bash
docker compose up --build
```

Normal run:

```bash
docker compose up
```

Detached run:

```bash
docker compose up -d
```

What starts:

| Service | Runs |
| --- | --- |
| `db` | PostgreSQL 16 |
| `object-storage` | Private persistent Garage S3-compatible Listing Media storage; initializes its private buckets and Product key |
| `product` | FastAPI Product, migrations, all background workers |
| `hermes` | Hermes runtime and Maia plugin |
| `site` | Public SSR site, private to Product |

The only customer/application entry point exposed to the host is:

```text
http://localhost:8080
```

For local object-storage administration only, Garage's S3 API binds to
`127.0.0.1:9000`. Its administration API stays inside the Compose network.
Site receives neither endpoint credentials nor direct bucket access.

### Migrate an existing MinIO volume once

An existing checkout may have the old `maia_object-storage-data` Docker volume.
Keep its old MinIO root credentials in `MINIO_MIGRATION_ROOT_USER` and
`MINIO_MIGRATION_ROOT_PASSWORD` in `.env`. Make a separate snapshot first and
point the migration profile at that copy:

```bash
docker volume create maia-object-storage-migration-copy
docker run --rm \
  -v maia_object-storage-data:/source:ro \
  -v maia-object-storage-migration-copy:/target \
  alpine:3.22 sh -c 'cp -a /source/. /target/'
printf '\nMINIO_LEGACY_VOLUME_NAME=maia-object-storage-migration-copy\n' >> .env
docker compose --profile storage-migration up -d object-storage legacy-object-storage
docker compose --profile storage-migration run --rm object-storage-migrate
docker compose --profile storage-migration stop legacy-object-storage
```

The migration image builds the exact MinIO server release previously pinned by
Compose, copies both Listing Media buckets into Garage, and verifies each
object's SHA-256 and length. It does not modify or delete the original volume.

Run this before starting Product against Garage. A new checkout with no old
MinIO volume can skip this migration.

When upgrading an existing checkout that still has the retired `listing-media`
volume, migrate only PostgreSQL-referenced objects before restarting Product:

```bash
docker compose up -d db object-storage
docker compose --profile migration run --rm --build media-migrate
docker compose up -d --build
```

The migration is idempotent, verifies every SHA-256, does not change PostgreSQL,
and does not delete the retired volume.

Load the coherent local inventory and CRM walkthrough through Product's real
commands (safe to repeat; it does not insert presentation-only fixtures):

```bash
docker compose run --rm -e WORKER_ENABLED=false product \
  python -m realestate.sandbox_seed --confirm-local-sandbox
```

The external checks are explicit. This variant refreshes provider-owned Meta
template truth and books one synthetic visit in the configured real Calendar:

```bash
docker compose run --rm -e WORKER_ENABLED=false product \
  python -m realestate.sandbox_seed --confirm-local-sandbox \
  --sync-meta-templates --book-calendar
```

## 3. Prove It Is Up

```bash
docker compose ps
curl -fsS http://localhost:8080/live
curl -fsS http://localhost:8080/health | python -m json.tool
curl -fsS http://localhost:8080/health/hermes | python -m json.tool
```

Follow logs:

```bash
docker compose logs -f product hermes site db object-storage
```

Check migrations:

```bash
docker compose exec product alembic current
docker compose exec product alembic heads
```

Check DB directly:

```bash
docker compose exec db psql -U realestate -d realestate -c '\dt'
```

## 4. Open The Human Surfaces

Public site, no auth:

```text
http://localhost:8080/
http://localhost:8080/propiedades
http://localhost:8080/propiedades?operation=Sale&zone=Zapopan
http://localhost:8080/guardadas
http://localhost:8080/maia
http://localhost:8080/robots.txt
http://localhost:8080/sitemap.xml
```

Operator surfaces, HTTP Basic auth with `<operator-login>:<local-password>`:

```text
http://localhost:8080/crm
http://localhost:8080/crm/bandeja
http://localhost:8080/crm/oportunidades
http://localhost:8080/crm/contactos
http://localhost:8080/crm/asignacion
http://localhost:8080/crm/catalogo
http://localhost:8080/crm/inventario-externo
http://localhost:8080/crm/reactivacion
http://localhost:8080/crm/bi
http://localhost:8080/crm/patrocinios
http://localhost:8080/crm/equipo
http://localhost:8080/crm/equipo/ausencias
http://localhost:8080/crm/equipo/especialistas
http://localhost:8080/crm/agenda
http://localhost:8080/crm/alertas
http://localhost:8080/crm/plataforma
http://localhost:8080/admin/properties
http://localhost:8080/upload
```

Market intelligence, HTTP Basic auth with
`MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON`:

```text
http://localhost:8080/market-intelligence
```

## 5. Exercise Product APIs

Use shell variables so secrets stay out of command history edits:

```bash
export MAIA_OPERATOR_LOGIN='<operator-login>'
export MAIA_DEV_PASSWORD='<local-password>'
export PLUGIN_API_TOKEN='<PLUGIN_API_TOKEN from .env>'
export PLATFORM_OPERATOR_TOKEN='<PLATFORM_OPERATOR_TOKEN from .env>'
```

Upload one property document:

```bash
curl -i -u "${MAIA_OPERATOR_LOGIN}:${MAIA_DEV_PASSWORD}" \
  -F "file=@tests/fixtures/casa-roble.md" \
  http://localhost:8080/upload
```

Check plugin -> Product:

```bash
curl -fsS \
  -H "Authorization: Bearer ${PLUGIN_API_TOKEN}" \
  http://localhost:8080/internal/plugin/health | python -m json.tool
```

Check platform API:

```bash
curl -fsS \
  -H "Authorization: Bearer ${PLATFORM_OPERATOR_TOKEN}" \
  -H "X-Platform-Operator: Guillermo local" \
  http://localhost:8080/platform/organizations | python -m json.tool
```

Check Meta webhook verification:

```bash
curl -fsS \
  "http://localhost:8080/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=${META_VERIFY_TOKEN}&hub.challenge=ok"
```

## 6. Run The Required Local Gate

```bash
docker compose exec product ruff check src plugin tests migrations
docker compose exec product mypy
docker compose exec product pytest \
  -m 'not live_provider and not live_external_inventory' \
  --strict-markers \
  --cov
```

Run by layer:

```bash
docker compose exec product pytest tests/api --strict-markers
docker compose exec product pytest tests/domain --strict-markers
docker compose exec product pytest tests/infrastructure --strict-markers
docker compose exec product pytest tests/integration --strict-markers
docker compose exec product pytest tests/migrations --strict-markers
docker compose exec product pytest tests/workers --strict-markers
```

## 7. Run Provider Opt-In Tests

These are not required for token-free local CI.

Real Hermes/model conversation tests:

```bash
docker compose exec -e RUN_CONVERSATION_TESTS=1 product pytest \
  tests/integration/test_sales_conversation.py \
  tests/integration/test_admin_conversation.py \
  -m live_provider \
  --strict-markers
```

Warning: these reset the development property inventory used by the running app.

EasyBroker staging read-only test:

```bash
export EASYBROKER_STAGING_API_KEY='<staging key>'
docker compose exec \
  -e RUN_EASYBROKER_LIVE_TESTS=1 \
  -e EASYBROKER_STAGING_API_KEY="${EASYBROKER_STAGING_API_KEY}" \
  product pytest tests/infrastructure/test_easybroker_live.py \
  -m live_external_inventory \
  --strict-markers
```

Production EasyBroker operation is split deliberately:

- `Sincronizar inventario propio de EasyBroker` reads the configured account's
  own `/properties` and does not require the API MLS add-on;
- `Sincronizar colaboradores de sólo lectura` reads `/mls_properties` and is
  refused unless API MLS access is explicitly confirmed;
- both paths are refused before the network call until external-payload
  retention is explicitly confirmed for the Brokerage Organization;
- synchronized rows are external candidates only. An Administrator must record
  authority, attribution, collaboration, availability and commission evidence;
  synchronization never publishes a Listing.

The controls and sanitized source health are available at
`http://localhost:8080/crm/inventario-externo`. The API key is never rendered.

Everything pytest can run with opt-ins:

```bash
docker compose exec \
  -e RUN_CONVERSATION_TESTS=1 \
  -e RUN_EASYBROKER_LIVE_TESTS=1 \
  -e EASYBROKER_STAGING_API_KEY="${EASYBROKER_STAGING_API_KEY}" \
  product pytest --strict-markers --cov
```

## 8. Stop, Restart, Reset

Stop but keep local data:

```bash
docker compose down
```

Restart cleanly:

```bash
docker compose down
docker compose up --build
```

Destroy all local Maia data:

```bash
docker compose down -v
```

## 9. Quick Failure Map

| Symptom | Check |
| --- | --- |
| Compose refuses to start | `.env` is missing an application or object-storage secret |
| `/health` is `degraded` | read `components`; DB/Hermes/object storage/background loop gate status |
| CRM asks for auth | use `<operator-login>:<local-password>` from `.env` |
| CRM returns 403 | `ORGANIZATION_*_LOGINS` does not include that Basic-auth login |
| `/platform/*` returns 401 | missing `PLATFORM_OPERATOR_TOKEN` or Bearer header |
| `/platform/*` returns 400 | missing `X-Platform-Operator` |
| Public pages are empty | load the local sandbox through `python -m realestate.sandbox_seed --confirm-local-sandbox` |
| Real conversation fails | `ANTHROPIC_API_KEY` or model/provider config is missing |
| Calendar booking refuses | `GOOGLE_CALENDAR_CREDENTIALS`, calendar id, or advisor calendar is missing |
