---
status: accepted
---

# Start with one modular backend

The initial product uses one modular backend, with background workers where
needed, rather than independently deploying its business modules. Inventory,
CRM, scheduling, messaging and conversational execution retain explicit
responsibilities and small interfaces. This keeps initial operations simple
while allowing a module to be extracted later if a demonstrated need warrants
the additional deployment and coordination cost.
