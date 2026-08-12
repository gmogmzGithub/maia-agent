# Maia Project Memory

This file is the public, curated memory for Maia. It is meant to help future
contributors and AI coding agents continue the project without relying on
private Codex memory.

## Name

The product name is **Maia**.

Reasoning:

- Maia is short, person-like, and easy in English and Spanish.
- It has a warm guide/operator feel that fits real estate conversations.
- It has a subtle mythological connection to Hermes without sounding like a
  derivative product name.

## Product Goal

Maia is a real estate lead agent for WhatsApp-driven property inquiries. It
should qualify leads, answer grounded property questions, schedule visits, and
follow up consistently.

The product is not just a chatbot. It is an agentic product where Hermes handles
conversation and the Maia backend provides deterministic authority.

## Current Stage

Local Stage 0 prototype.

Implemented locally:

- FastAPI product backend;
- PostgreSQL persistence;
- Alembic migrations;
- property document ingestion;
- Hermes runtime integration over local JSON-RPC;
- standalone Hermes plugin for Maia tools;
- WhatsApp webhook handling and durable delivery workflow;
- Google Calendar availability and appointment booking;
- Telegram administrative role;
- deterministic lead follow-up worker;
- Docker Compose single-host topology;
- pytest suite for domain, API, worker, plugin, and channel behavior.

Not yet proven or claimed:

- production deployment;
- real customer pilot;
- cloud-managed operations;
- legal/privacy readiness for real lead data;
- multi-tenant operation;
- horizontal scaling.

## Core Boundary

Hermes owns:

- natural-language reasoning;
- memory/session continuity;
- interpreting fragmented WhatsApp messages;
- selecting tools;
- composing user-facing Spanish replies.

Maia owns:

- trusted channel identity;
- PostgreSQL truth;
- business rules;
- property document acceptance;
- appointment authority;
- follow-up cadence;
- Meta/Calendar/Telegram side effects;
- retry and ambiguity classification;
- audit trail.

This boundary is the central design decision. Do not let the model directly own
business truth or side effects.

## Public Repository Positioning

This repository is intended to be visible to recruiters and hiring managers.
The public story should emphasize:

- backend/platform engineering for AI products;
- typed tool authority beneath agentic conversation;
- durable workflow design;
- external API integration;
- recovery and operational thinking;
- pragmatic separation between model behavior and system authority.

Avoid public wording that overclaims:

- production readiness;
- legal compliance;
- real customer deployment;
- guaranteed model accuracy;
- autonomous business authority.

## Branching Policy

Use:

- `main` for public, recruiter-visible material;
- `codex/<topic>` or `feature/<topic>` for normal implementation work;
- `private/<topic>` for local/private notes that must not be merged into
  `main`.

`main` should contain clean product code, public-safe docs, and reproducible
development instructions. Private notes, raw memory, and rough planning belong
outside `main`.

## Open Next Work

- Rename Python package and plugin identifiers from the original
  `realestate`/`realestate-hermes-plugin` naming to Maia-specific names if the
  project moves beyond this port.
- Add GitHub Actions once the public repo has its first stable commit.
- Decide whether the first public demo should use synthetic property fixtures,
  screenshots, or a short architecture walkthrough.
- Add deployment documentation only after a live target exists and has been
  tested.
