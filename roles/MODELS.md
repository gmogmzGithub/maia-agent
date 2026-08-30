# Which model for which Role

Set the models in `.env`; the Hermes container builds the corresponding
profiles whenever it starts:

```bash
SALES_MODEL=claude-haiku-4-5-20251001
ADMIN_MODEL=claude-haiku-4-5-20251001
MODEL_PROVIDER=anthropic
```

After changing a model or a Role guide, rebuild/recreate Hermes:

```bash
docker compose up -d --build --force-recreate hermes
```

## Current setting: Haiku 4.5 for both

Chosen deliberately for cost during Stage 0 development. It is a good default:
both Roles work, and the measured differences below are narrow.

## When to move the Sales Role to Sonnet

The Sales Role is the only one a customer ever reads. Move it to Sonnet
(`SALES_MODEL=claude-sonnet-5`) when any of these start to matter:

**1. Before the live pilot with real Leads.** Recommended. Real customers see
this output; the Administrative Role is only ever read by internal operators,
where a clumsy sentence costs nothing.

**2. Approved copy.** Not a reason to switch any more. The discovery documents
write the P-049 clarification with a capital `NO`; that was treated as an
operator typing habit, not intended customer-facing copy. The model's natural
phrasing is preferred. The requirement is now the *behaviour* — ask which
Property, name none, leak no facts — which measures **4/4 on Haiku**.

The Harness still canonicalises approved copy at settlement
(`domain/copy.py`), so accent, punctuation, and casing drift is normalised to
one form before release. It repairs rewording; it cannot invent a sentence the
model never wrote, and it never decides that a reply *should* have been an
approved message.

Do **not** add a guide instruction about capitalisation. That was measured: it
made adherence worse (1/4), because pointing at an oddity invites the model to
correct it.

**3. Spanish register.** Haiku slipped into Argentine voseo (*"Tenés"*,
*"¿Cuál querés activar?"*) on the Administrative Role until the guide pinned
Mexican Spanish and `tú` explicitly. Harmless internally; not something to ship
to a Guadalajara Lead.

## Where Haiku is actually better

One measured case runs the other way. After a Property is deactivated, the Sales
Role must stop repeating facts it already gave — including facts it stated
earlier in the same conversation.

* **Haiku 4.5** passes this on a conversation already primed with the price.
* **Sonnet 5** leans harder on conversation history and repeats the price.

So Sonnet is not a strict upgrade. If you switch the Sales Role to Sonnet,
re-run the disclosure test specifically:

```bash
docker compose exec -e RUN_CONVERSATION_TESTS=1 product pytest \
  tests/integration/test_sales_conversation.py -k inactive
```

## The Administrative Role

Haiku is the right default and there is no measured reason to change it. It
talks only to two people who can ask again if a reply is unclear, it performs no
customer-facing copy, and its consequential action — a status change — is
constrained by the Backend rather than by model judgment.

## Re-measuring

Both suites are opt-in because they call the real model:

```bash
docker compose exec -e RUN_CONVERSATION_TESTS=1 product pytest \
  tests/integration/test_sales_conversation.py tests/integration/test_admin_conversation.py
```

Behaviour is probabilistic. A single run is an anecdote — run a check four or
five times before concluding a model changed something.
