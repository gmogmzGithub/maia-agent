# Maia Agent - Development Guide

Instructions for AI coding assistants and developers working on this repository.

## Product Identity

The product name is **Maia**.

Maia is a Hermes-backed real estate lead agent. It handles WhatsApp inquiries,
answers from approved property documents, schedules visits, and coordinates
follow-ups. The product should feel like a capable real estate operator, not an
AI novelty.

## Public Repository Rule

This repository is intended to be public and recruiter-visible.

Do not commit:

- raw Codex memory files or session transcripts;
- local Hermes runtime state from `hermes-home/`;
- `.env`, tokens, credentials, or provider keys;
- real lead data, real customer conversations, or private property documents;
- private planning notes that are not meant for hiring managers;
- generated databases, lock files, caches, or local artifacts.

Use `PROJECT_MEMORY.md` for curated project decisions that are safe to publish.
Put private notes outside this repository or on a private branch that is never
merged into `main`.

## Architecture Boundary

Preserve the Product/Hermes split.

Hermes owns:

- natural-language understanding;
- session continuity;
- fragmented-message reconciliation;
- clarification;
- time interpretation;
- tool selection;
- response composition.

Maia owns:

- trusted identity;
- PostgreSQL truth;
- Inbox/Outbox state;
- authorization;
- deterministic business policy;
- audit events;
- Calendar and Meta side effects;
- retries, ambiguity handling, and safety outcomes.

The model may request operations through typed tools. It must not directly own
database writes, Calendar credentials, WhatsApp delivery, or business truth.

## Implementation Style

- Keep the MVP simple and operational.
- Prefer deterministic backend authority beneath natural-language interaction.
- Do not replace Hermes with a rigid intent classifier or dialogue tree.
- Keep the standalone Hermes plugin thin. It exposes typed operations to Hermes
  and calls the Product API; it must not import the Product database layer or
  own business rules.
- Use PostgreSQL as the product system of record.
- Keep `.env` for secrets only. Non-secret behavior belongs in code defaults,
  docs, or explicit configuration.
- Add tests around behavior contracts and recovery paths, not fragile snapshots.

## Local Development

Use the repo-local virtual environments:

```bash
scripts/bootstrap.sh
source .venv/bin/activate
PYTHONPATH=. pytest
```

`scripts/bootstrap.sh` creates:

- `.venv` for the Maia FastAPI backend;
- `.venv-hermes` for the pinned Hermes runtime plus the Maia plugin;
- `.env` with local generated secrets if one does not exist.

The default Hermes checkout is `~/workspace/repos/hermes-agent`; override with
`HERMES_CHECKOUT` in `.env` when needed.

## Git Hygiene

Default public branch: `main`.

Recommended private branch prefix: `private/`.
Recommended implementation branch prefix: `codex/` or `feature/`.

Before committing, check:

```bash
git status --short
git diff --stat
git diff -- . ':!PROJECT_MEMORY.md'
```

Never add ignored runtime state with force unless the user explicitly asks and
the file is verified public-safe.
