# Source Layout

`realestate` is the Maia Product package. Its folder names are part of the
architecture:

- `api/`: FastAPI routers and server-rendered operator surfaces.
- `domain/`: Product authority and business rules.
- `db/`: persistence adapter, SQLAlchemy engine, and ORM model definitions.
- `worker/`: background workers and polling orchestration.
- `channels/`: WhatsApp, Telegram, and Google Calendar adapters.
- `hermes/`: Product-side Hermes client and session binding.
- `site/`: server-rendered public web experience, templates, assets, and Product
  gateway.

Keep routers, workers, templates, and channel adapters thin. A decision that
changes Product truth belongs in `domain/`; a concrete external system belongs
in an adapter package.
