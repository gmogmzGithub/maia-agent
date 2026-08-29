# Migrations

This directory contains Maia's Alembic migration environment and revision
history.

- `env.py` wires Alembic to the Product database settings and ORM metadata.
- `versions/` contains ordered schema revisions.
- `script.py.mako` is Alembic's revision template.

Keep migrations deterministic and reversible where the product contract requires
it. Any model split or persistence cleanup must still leave Alembic able to load
the full `realestate.db.models` registry.
