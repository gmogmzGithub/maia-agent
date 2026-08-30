# Channel Adapters

This package contains concrete adapters for external systems.

- `whatsapp/`: Meta WhatsApp payloads, signatures, formatting, templates, and
  Cloud API client behavior.
- `telegram/`: Telegram administrative channel client.
- `google/`: Google Calendar adapter.

Adapters translate provider contracts into Maia's internal contracts. They do
not own business authority, Organization routing, customer consent, or retry
policy.
