# Test Layout

The tests are grouped by the layer or behavior they protect:

- `api/`: HTTP routes, operator pages, plugin tools, upload/webhook surfaces,
  and public-site rendering contracts.
- `domain/`: Product policy, authorization, invariants, privacy, catalog,
  commercial, platform, analytics, sponsorship, engagement, and scheduling
  behavior.
- `infrastructure/`: persistence, channel adapters, Hermes client/session
  integration, payload parsing, formatting, and low-level transport contracts.
- `integration/`: vertical flows and app lifecycle tests.
- `migrations/`: Alembic revision behavior and migrated schema compatibility.
- `workers/`: background loop and worker orchestration.
- `fixtures/`: shared builders, fakes, and test data helpers.

Run all required tests through the existing gate:

```bash
docker compose exec product pytest \
  -m 'not live_provider and not live_external_inventory' --strict-markers --cov
```

Prefer shared helpers in `tests/fixtures/`. Avoid importing one test module from
another; that turns the test tree into an accidental dependency graph.
