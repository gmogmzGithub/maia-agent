# Persistence

This package is Maia's persistence adapter.

- `engine.py` owns SQLAlchemy engine/session setup and database health.
- `models.py` owns the ORM registry used by Alembic and the Product domain.

`models.py` is intentionally still a single registry module in this cleanup
pass. Splitting it is a worthwhile follow-up, but it must preserve
`realestate.db.models` as the import surface, keep Alembic metadata complete,
and run the migration compatibility tests after every split.
