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
DEVELOPER_BASIC_CREDENTIALS_JSON={"developer":"<local-password>"}
ORGANIZATION_ADMIN_LOGINS=developer
ORGANIZATION_ADVISOR_LOGINS=developer
ORGANIZATION_DEFAULT_ADVISOR_LOGIN=developer
SITE_DESIGN_DEMO=true
```

Optional real-provider values:

```dotenv
ANTHROPIC_API_KEY=<real Anthropic key>
META_VERIFY_TOKEN=<Meta webhook verify token>
META_APP_SECRET=<Meta app secret>
META_ACCESS_TOKEN=<Meta access token>
META_PHONE_NUMBER_ID=<Meta phone number id>
META_WABA_ID=<WhatsApp Business Account id>
TELEGRAM_BOT_TOKEN=<Telegram bot token>
TELEGRAM_ADMIN_IDS=<comma-separated Telegram user ids>
GOOGLE_CALENDAR_CREDENTIALS=/run/secrets/google-calendar.json
GOOGLE_CALENDAR_ID=<calendar id>
EASYBROKER_API_KEY=<EasyBroker key>
PLATFORM_OPERATOR_TOKEN=<local platform operator token>
MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON={"analyst":"<local-password>"}
```

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
| `product` | FastAPI Product, migrations, all background workers |
| `hermes` | Hermes runtime and Maia plugin |
| `site` | Public SSR site, private to Product |

Only this is exposed to the host:

```text
http://localhost:8080
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
docker compose logs -f product hermes site db
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

Operator surfaces, HTTP Basic auth with `developer:<local-password>`:

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
export MAIA_DEV_PASSWORD='<local-password>'
export PLUGIN_API_TOKEN='<PLUGIN_API_TOKEN from .env>'
export PLATFORM_OPERATOR_TOKEN='<PLATFORM_OPERATOR_TOKEN from .env>'
```

Upload one property document:

```bash
curl -i -u "developer:${MAIA_DEV_PASSWORD}" \
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
| Compose refuses to start | `.env` is missing one of the three local tokens |
| `/health` is `degraded` | read `components` in `/health`; DB/Hermes/background loop gate status |
| CRM asks for auth | use `developer:<local-password>` |
| CRM returns 403 | `ORGANIZATION_*_LOGINS` does not include that Basic-auth login |
| `/platform/*` returns 401 | missing `PLATFORM_OPERATOR_TOKEN` or Bearer header |
| `/platform/*` returns 400 | missing `X-Platform-Operator` |
| Public pages are empty | set `SITE_DESIGN_DEMO=true` for local visual review |
| Real conversation fails | `ANTHROPIC_API_KEY` or model/provider config is missing |
| Calendar booking refuses | `GOOGLE_CALENDAR_CREDENTIALS`, calendar id, or advisor calendar is missing |
