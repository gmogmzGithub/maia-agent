"""Creating, trusting, and prompting a Hermes Role session.

A Role session is created through the pinned JSON-RPC contract and immediately
bound, in PostgreSQL, to the product Role it serves. When the plugin later
forwards Hermes's ``session_id``, the Product application looks it up here — so
Role authority comes from a record the product wrote, never from a model
argument (TC-008).

``session.create`` returns two identifiers and both matter:

* ``session_id`` — the gateway handle used for ``prompt.submit`` and
  ``session.steer``;
* ``stored_session_id`` — the durable agent session id, and the exact value
  Hermes passes to plugin tool handlers as ``session_id``
  (``tui_gateway/server.py`` builds the agent with ``session_id=session_key``).

The binding is keyed on ``stored_session_id`` for that reason.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AgentRole, AgentSession
from realestate.domain.copy import SPANISH_DAYS
from realestate.hermes.client import HermesClient

logger = logging.getLogger(__name__)

# A model turn can legitimately take a while; this is a local-development
# ceiling, not a product policy.
TURN_TIMEOUT_SECONDS = 240.0

SALES_FRESHNESS_CONTEXT = (
    "[Contexto obligatorio del producto para este turno: si el mensaje pide "
    "cualquier dato de una propiedad, llama a get_property_information antes "
    "de responder. Los datos de turnos anteriores no están vigentes hasta "
    "revalidarlos con esa herramienta en este turno.]"
)


class SessionError(RuntimeError):
    """A Hermes session operation failed."""


@dataclass(frozen=True)
class RoleSession:
    gateway_session_id: str
    hermes_session_id: str
    role: AgentRole


@dataclass
class TurnResult:
    text: str
    tools_used: list[str] = field(default_factory=list)
    injected: list[str] = field(default_factory=list)
    # The durable session the turn actually ran on. Differs from the one asked
    # for only when the old one was unrecoverable and a new one was created;
    # the caller must then re-point its binding.
    hermes_session_id: str = ""


def trusted_context(*, profile_name: str | None) -> list[dict[str, str]]:
    """Seed history carrying what the product knows and the Model cannot.

    A WhatsApp profile name is trusted state: it arrives on the webhook and lives
    on the Lead row. The Model has no other way to learn it, so without this it
    would have to invent one — and an invented name is exactly what a display
    field must never contain (amendment 3).

    It is supplied as one ``system`` seed message at session creation, which
    upstream ``session.create`` accepts natively (``messages``), so no Hermes
    change is involved. Deliberately narrow: this seam carries display context
    only. It grants nothing, and identity for authorization still resolves from
    the session binding in PostgreSQL, never from anything the Model can read or
    repeat back (ADR-0009, P-061).
    """
    if not profile_name or not profile_name.strip():
        return []
    return [
        {
            "role": "system",
            "content": (
                "Contexto del producto, no es un mensaje de la persona y no "
                "requiere respuesta: su nombre de perfil de WhatsApp es "
                f"«{profile_name.strip()}». Es un nombre para dirigirte a ella "
                "con cortesía y para ofrecerlo al agendar una cita. No es un "
                "dato verificado de identidad y no confirma quién es."
            ),
        }
    ]


def dated_prompt(text: str, *, today: date) -> str:
    """Prefix one turn's text with the current local date.

    The Model cannot convert "el viernes por la tarde" into ``date_from`` without
    knowing what day it is, and it has no clock. Hermes's own system prompt ends
    with "Conversation started: …", which is not the same thing: a Lead
    Engagement Cycle runs for 30 days, so on day nine that line is nine days
    stale and using it would book the wrong week.

    Left unsaid, the failure is quiet and expensive. A rehearsal produced
    «necesito saber cuál es el próximo domingo», a guessed date, an empty
    candidate list, and the Agent telling the Lead there was no availability at
    all — while the calendar was completely free.

    ``prompt.submit`` takes only ``session_id`` and ``text``, so the date rides
    the text as one delimited line. The Lead's own words are untouched below it,
    and the Inbox rows that record what the Lead actually said are unaffected.
    """
    stamp = f"{SPANISH_DAYS[today.weekday()]} {today.strftime('%d/%m/%Y')} ({today.isoformat()})"
    return f"[Contexto del producto — hoy es {stamp}]\n{text}"


def role_prompt(text: str, *, role: AgentRole) -> str:
    """Attach repeatable Product safety context without replacing Lead text.

    Hermes keeps the complete conversation and still decides whether a message
    asks about a Property. The Product repeats the freshness contract on every
    Sales turn because a Property Document or status may change while that
    durable session remains open. An instruction that appears only in SOUL.md
    can lose salience behind already-retrieved facts in a long conversation.
    """
    if role is AgentRole.SALES:
        return f"{SALES_FRESHNESS_CONTEXT}\n{text}"
    return text


async def _attach(
    rpc,
    hermes_session_id: str,
    profile: str,
    seed: list[dict[str, str]] | None = None,
    minimum_history_messages: int = 0,
) -> tuple[str, str]:
    """Get a live gateway handle for a durable session on *this* connection.

    A gateway handle belongs to the WebSocket that created it: closing the
    socket reaps the session (``tui_gateway/ws.py`` calls
    ``_close_sessions_for_transport`` in its ``finally``). Persisting a handle
    and reusing it on a later connection therefore always fails with "session
    not found". The durable ``stored_session_id`` is the thing that survives, so
    every turn re-attaches to it here and works with a handle valid for the
    connection it is on.

    Returns ``(gateway_session_id, durable_session_id)``. The durable id changes
    only when the old session could not be resumed at all.

    ``seed`` is only ever applied on the create path. A resumed session already
    carries it in its own history, and re-seeding would repeat the context every
    time a gateway handle was reaped.
    """
    if hermes_session_id:
        logger.debug(
            "Attaching to existing Hermes durable session (profile=%s, durable=%s)",
            profile,
            hermes_session_id,
        )
        frame = await rpc.call(
            "session.resume",
            {"session_id": hermes_session_id, "profile": profile, "omit_messages": True},
        )
        result = frame.get("result") or {}
        history_is_complete = int(result.get("message_count") or 0) >= minimum_history_messages
        if not frame.get("error") and result.get("session_id") and history_is_complete:
            durable = result.get("session_key") or result.get("resumed") or hermes_session_id
            logger.debug(
                "Resumed Hermes session (profile=%s, gateway=%s, durable=%s)",
                profile,
                result["session_id"],
                durable,
            )
            return str(result["session_id"]), str(durable)
        if not frame.get("error") and result.get("session_id"):
            logger.error(
                "Hermes session history is incomplete; rebuilding from Product records "
                "(profile=%s, durable=%s, observed=%s, expected_at_least=%d)",
                profile,
                hermes_session_id,
                result.get("message_count"),
                minimum_history_messages,
            )
        else:
            logger.warning(
                "Could not resume Hermes durable session; creating a replacement "
                "(profile=%s, durable=%s, error=%s)",
                profile,
                hermes_session_id,
                frame.get("error") or "missing session_id",
            )

    # No durable session yet (Hermes persists the row lazily, on the first
    # prompt) or it is genuinely gone. Start one.
    create: dict[str, object] = {"profile": profile, "source": "product"}
    if seed:
        create["messages"] = seed
    logger.info(
        "Creating Hermes Role session (profile=%s, seed_messages=%d)",
        profile,
        len(seed or ()),
    )
    frame = await rpc.call("session.create", create)
    if frame.get("error"):
        logger.error("Hermes session.create failed (profile=%s, error=%s)", profile, frame["error"])
        raise SessionError(f"session.create failed: {frame['error']}")
    result = frame.get("result") or {}
    gateway = result.get("session_id")
    durable = result.get("stored_session_id")
    if not gateway or not durable:
        logger.error(
            "Hermes session.create returned unusable identifiers (profile=%s, result=%r)",
            profile,
            result,
        )
        raise SessionError(f"session.create returned no usable identifiers: {result!r}")
    logger.info(
        "Created Hermes Role session (profile=%s, gateway=%s, durable=%s)",
        profile,
        gateway,
        durable,
    )
    return str(gateway), str(durable)


async def session_for_cycle(db: AsyncSession, cycle_id: uuid.UUID) -> RoleSession:
    """The cycle's Sales session binding, as far as it is known.

    No Hermes call happens here. A cycle's first turn has no durable session
    yet, so ``hermes_session_id`` starts empty and ``_attach`` fills it in on
    the connection that runs the turn; :func:`bind_cycle_session` then persists
    it. Creating a session on a throwaway connection would only have it reaped.
    """
    binding = (
        await db.execute(select(AgentSession).where(AgentSession.cycle_id == cycle_id))
    ).scalar_one_or_none()
    return RoleSession(
        gateway_session_id="",
        hermes_session_id=binding.hermes_session_id if binding else "",
        role=AgentRole.SALES,
    )


async def bind_session(
    db: AsyncSession,
    *,
    role: AgentRole,
    hermes_session_id: str,
    cycle_id: uuid.UUID | None = None,
    channel_key: str | None = None,
) -> None:
    """Point the binding identified by *cycle_id* or *channel_key* at a session.

    This is what makes the plugin's trusted-context lookup resolve, so it must
    be committed before the model gets a chance to call a tool. Every kind of
    binding — a Sales Engagement Cycle, an administrative channel — upserts
    through here, so that ordering requirement is stated once.
    """
    if (cycle_id is None) == (channel_key is None):
        raise ValueError("bind_session needs exactly one of cycle_id or channel_key")

    key = (
        AgentSession.cycle_id == cycle_id
        if cycle_id is not None
        else AgentSession.channel_key == channel_key
    )
    binding = (await db.execute(select(AgentSession).where(key))).scalar_one_or_none()
    if binding is None:
        logger.info(
            "Binding Hermes session to product role "
            "(role=%s, durable=%s, cycle_id=%s, channel_key=%s)",
            role.value,
            hermes_session_id,
            cycle_id,
            channel_key,
        )
        db.add(
            AgentSession(
                hermes_session_id=hermes_session_id,
                role=role.value,
                cycle_id=cycle_id,
                channel_key=channel_key,
            )
        )
    else:
        logger.info(
            "Updating Hermes session binding "
            "(role=%s, old_durable=%s, new_durable=%s, cycle_id=%s, channel_key=%s)",
            role.value,
            binding.hermes_session_id,
            hermes_session_id,
            cycle_id,
            channel_key,
        )
        binding.hermes_session_id = hermes_session_id
    await db.commit()


async def bind_cycle_session(
    db: AsyncSession, *, cycle_id: uuid.UUID, hermes_session_id: str
) -> None:
    """Bind a Sales Engagement Cycle to *hermes_session_id*."""
    await bind_session(
        db,
        role=AgentRole.SALES,
        hermes_session_id=hermes_session_id,
        cycle_id=cycle_id,
    )


async def bind_channel_session(
    db: AsyncSession, *, role: AgentRole, channel_key: str, hermes_session_id: str
) -> None:
    """Bind an administrative channel (``telegram:<chat id>``) to a session."""
    await bind_session(
        db,
        role=role,
        hermes_session_id=hermes_session_id,
        channel_key=channel_key,
    )


async def find_role_session(db: AsyncSession, role: AgentRole) -> RoleSession | None:
    """Return the most recently bound session for *role*, if any."""
    binding = (
        await db.execute(
            select(AgentSession)
            .where(AgentSession.role == role.value)
            .order_by(AgentSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if binding is None:
        return None
    return RoleSession(
        gateway_session_id=binding.gateway_session_id or "",
        hermes_session_id=binding.hermes_session_id,
        role=role,
    )


async def run_turn(
    client: HermesClient,
    session: RoleSession,
    text: str,
    *,
    profile: str,
    on_attached: "Callable[[str], Awaitable[None]] | None" = None,
    on_poll: "Callable[[], Awaitable[str | None]] | None" = None,
    on_adopted: "Callable[[], Awaitable[None]] | None" = None,
    seed: list[dict[str, str]] | None = None,
    minimum_history_messages: int = 0,
    window_seconds: float = 0.0,
    poll_interval: float = 0.4,
) -> TurnResult:
    """Run one turn, optionally folding late-arriving text into it.

    While ``window_seconds`` has not elapsed since the turn started, ``on_poll``
    is called between event polls. If it returns text, that text is injected
    into the *live* turn rather than becoming a second turn — this is the
    In-flight Message Reconciliation window (P-034).

    Injection prefers ``session.redirect``, the stronger primitive, and falls
    back to ``session.steer``. If neither accepts, nothing is reported as
    injected and the caller leaves the message queued for the next FIFO cycle.

    ``on_adopted`` fires immediately after a successful injection, before the
    next poll. That ordering matters: without it the same still-pending message
    would be seen again on the following poll and injected twice.
    """
    prompt_text = role_prompt(text, role=session.role)
    async with client.session() as rpc:
        logger.info(
            "Starting Hermes turn "
            "(role=%s, profile=%s, existing_durable=%s, text_chars=%d, window=%.2fs)",
            session.role.value,
            profile,
            session.hermes_session_id or "<new>",
            len(prompt_text),
            window_seconds,
        )
        # Attach on this connection: the handle is only valid here.
        sid, durable = await _attach(
            rpc,
            session.hermes_session_id,
            profile,
            seed,
            minimum_history_messages,
        )

        # Publish the durable id BEFORE prompting. The plugin resolves Role from
        # this binding, so a tool call in the very first model step would be
        # rejected as `forbidden` if the binding were written afterwards.
        if on_attached is not None and durable != session.hermes_session_id:
            logger.debug(
                "Publishing new Hermes durable session before prompt (profile=%s, durable=%s)",
                profile,
                durable,
            )
            await on_attached(durable)

        logger.debug(
            "Submitting prompt to Hermes (gateway=%s, durable=%s, text_chars=%d)",
            sid,
            durable,
            len(prompt_text),
        )
        frame = await rpc.call(
            "prompt.submit", {"session_id": sid, "text": prompt_text}
        )
        if error := frame.get("error"):
            logger.error("Hermes prompt.submit failed (gateway=%s, error=%s)", sid, error)
            raise SessionError(f"prompt.submit failed: {error}")

        started = time.monotonic()
        deltas: list[str] = []
        tools_used: list[str] = []
        injected: list[str] = []

        while True:
            params = await rpc.receive_event_or_none(poll_interval)

            if params is None:
                if time.monotonic() - started > TURN_TIMEOUT_SECONDS:
                    logger.error(
                        "Hermes turn timed out (gateway=%s, durable=%s, elapsed=%.2fs)",
                        sid,
                        durable,
                        time.monotonic() - started,
                    )
                    raise SessionError("Hermes did not complete the turn in time")
                if on_poll is not None and (time.monotonic() - started) < window_seconds:
                    late = await on_poll()
                    if late:
                        logger.debug(
                            "Late message observed during reconciliation window "
                            "(gateway=%s, chars=%d)",
                            sid,
                            len(late),
                        )
                    if late and await _inject(rpc, sid, late):
                        logger.info(
                            "Injected late message into active Hermes turn "
                            "(gateway=%s, chars=%d)",
                            sid,
                            len(late),
                        )
                        injected.append(late)
                        if on_adopted is not None:
                            await on_adopted()
                continue

            if params.get("session_id") not in (sid, None):
                logger.debug(
                    "Ignoring Hermes event for another session (expected=%s, got=%s)",
                    sid,
                    params.get("session_id"),
                )
                continue
            payload = params.get("payload") or {}
            event = params.get("type")

            if event == "message.delta":
                deltas.append(str(payload.get("text") or ""))
            elif event == "tool.start":
                if name := payload.get("name"):
                    tools_used.append(str(name))
                    logger.info(
                        "Hermes tool started (gateway=%s, durable=%s, tool=%s)",
                        sid,
                        durable,
                        name,
                    )
            elif event == "message.complete":
                if payload.get("status") == "error":
                    logger.error(
                        "Hermes turn completed with error (gateway=%s, error=%s)",
                        sid,
                        payload.get("error") or payload,
                    )
                    raise SessionError(
                        f"Hermes turn failed: {payload.get('error') or payload}"
                    )
                text_out = str(payload.get("text") or "".join(deltas))
                logger.info(
                    "Hermes turn complete "
                    "(gateway=%s, durable=%s, response_chars=%d, tools=%s, injected=%d)",
                    sid,
                    durable,
                    len(text_out),
                    ",".join(tools_used) or "none",
                    len(injected),
                )
                return TurnResult(
                    text=text_out,
                    tools_used=tools_used,
                    injected=injected,
                    hermes_session_id=durable,
                )


async def _inject(rpc, sid: str, text: str) -> bool:  # type: ignore[no-untyped-def]
    """Fold *text* into the running turn. False when Hermes would not take it."""
    for method, accepted_states in (
        ("session.redirect", {"redirected", "queued"}),
        ("session.steer", {"queued"}),
    ):
        logger.debug("Trying Hermes live-turn injection (method=%s, gateway=%s)", method, sid)
        frame = await rpc.call(method, {"session_id": sid, "text": text})
        if frame.get("error"):
            logger.warning(
                "Hermes live-turn injection rejected (method=%s, gateway=%s, error=%s)",
                method,
                sid,
                frame.get("error"),
            )
            continue
        if (frame.get("result") or {}).get("status") in accepted_states:
            return True
    logger.warning("Hermes would not accept live-turn injection (gateway=%s)", sid)
    return False


async def bind_role_session(
    db: AsyncSession, *, role: AgentRole, hermes_session_id: str
) -> None:
    """Bind a cycle-less Role session (the local exercise and evaluation path)."""
    existing = (
        await db.execute(
            select(AgentSession).where(
                AgentSession.hermes_session_id == hermes_session_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            AgentSession(hermes_session_id=hermes_session_id, role=role.value)
        )
        await db.commit()


async def submit_prompt(
    client: HermesClient,
    session: RoleSession,
    text: str,
    *,
    profile: str = "sales",
    on_attached: "Callable[[str], Awaitable[None]] | None" = None,
) -> TurnResult:
    """Send one turn with no reconciliation window.

    Used by the local Sales exercise script and the evaluation suite. Shares
    ``run_turn``'s attach logic, so it is subject to exactly the same session
    lifecycle as the worker.
    """
    return await run_turn(
        client, session, text, profile=profile, on_attached=on_attached
    )
