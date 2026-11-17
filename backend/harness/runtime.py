"""Bounded agent loop: authorized tools, one complete reply, one output repair."""

import asyncio
import json
import logging
import time

import anthropic
from asgiref.sync import sync_to_async
from django.conf import settings
from pydantic import ValidationError

from agent.tools import FINAL_TOOL, TOOLS
from datalayer.errors import Superseded
from datalayer.replies import validate_reply
from datalayer.turns import finish_turn, load_turn, pending_turn_delay
from harness.memory.context import build_context, build_messages
from harness.replies.diagnostics import rejection_reason
from harness.replies.recovery import recovery_reply
from harness.tools import TurnTools

logger = logging.getLogger(__name__)


class MissingCredentials(Exception):
    pass


async def debounce(conversation_id):
    wait = await pending_turn_delay(conversation_id)
    if wait > 0:
        await asyncio.sleep(wait)
        await debounce(conversation_id)


def repair_message(calls, detail):
    results = [{"type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                "content": "Propuesta rechazada; ninguna llamada de este lote se ejecutó."}
               for call in calls]
    results.append({"type": "text", "text": (
        "Control del harness: la respuesta anterior no se publicó. "
        "Corrige solo propose_reply, sin operaciones nuevas. Usa los resultados existentes. "
        "El texto debe corresponder a fichas, controles y pendiente. Error: " + detail[:600]
    )})
    return {"role": "user", "content": results}


async def attend(conversation_id, client=None, *, group_messages=True):
    started = time.monotonic()
    if group_messages:
        await debounce(conversation_id)
    turn = await sync_to_async(load_turn)(conversation_id)
    if turn is None:
        return
    usage, events, cards = [0, 0], [], []
    status, error_code, text, reply = "completed", "", "", None
    final_only = False
    owns_client = client is None
    tools = TurnTools(conversation_id, turn)
    try:
        if client is None:
            if not settings.ANTHROPIC_API_KEY:
                raise MissingCredentials
            client = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY, max_retries=0, timeout=45
            )
        system = build_context(turn)
        messages = build_messages(turn)
        remaining = settings.TURN_TIMEOUT_SECONDS - (time.monotonic() - started)
        async with asyncio.timeout(max(0.1, remaining)):
            for _ in range(8):
                for attempt in range(3):
                    try:
                        response = await client.messages.create(
                            model=settings.ANTHROPIC_MODEL, system=system, messages=messages,
                            tools=[FINAL_TOOL] if final_only else TOOLS, max_tokens=2400,
                            tool_choice=({"type": "tool", "name": "propose_reply"}
                                         if final_only else {"type": "any"}),
                            thinking={"type": "disabled"},
                        )
                        break
                    except (anthropic.APIConnectionError, anthropic.RateLimitError,
                            anthropic.InternalServerError):
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2**attempt)
                usage[0] += response.usage.input_tokens
                usage[1] += response.usage.output_tokens
                blocks = [b.model_dump(exclude_none=True) for b in response.content]
                calls = [b for b in blocks if b["type"] == "tool_use"]
                messages.append({"role": "assistant", "content": blocks})
                finals = [c for c in calls if c["name"] == "propose_reply"]
                try:
                    if response.stop_reason == "max_tokens":
                        raise ValueError("generation truncated; no calls executed")
                    if not calls:
                        raise ValueError("finish using propose_reply, not free text")
                    if response.stop_reason != "tool_use":
                        raise ValueError("unexpected stop reason for a tool batch")
                    if finals:
                        if len(calls) != 1:
                            raise ValueError("propose_reply must be the only tool in its response")
                        reply, text, selected_cards = await sync_to_async(validate_reply)(
                            conversation_id, turn["revision"], finals[0]["input"], tools.cards
                        )
                        cards = selected_cards
                        events.append({"tool": "reply_validation", "outcome": "accepted",
                                       "corrected": final_only,
                                       "previous_pending": (turn["continuity"] or {}).get("pending"),
                                       "continuity": reply.continuity.model_dump(mode="json")})
                        break
                    if final_only:
                        raise ValueError("output repair cannot execute business tools")
                except (ValidationError, ValueError, KeyError, TypeError) as exc:
                    reason = rejection_reason(exc)
                    events.append({"tool": "reply_validation", "outcome": "rejected",
                                   "corrected": final_only, "error": type(exc).__name__,
                                   "reason": reason, "stop_reason": response.stop_reason,
                                   "tool_names": [c["name"] if c["name"] in {
                                       t["name"] for t in TOOLS
                                   } else "unknown_tool" for c in calls]})
                    logger.warning("reply_rejected conversation=%s reason=%s corrected=%s stop_reason=%s",
                                   conversation_id, reason, final_only, response.stop_reason)
                    if final_only:
                        reply = recovery_reply(tools.cards, tools.recovery_control)
                        reply, text, cards = await sync_to_async(validate_reply)(
                            conversation_id, turn["revision"], reply.model_dump(mode="json"), tools.cards
                        )
                        error_code = "reply_recovery"
                        break
                    final_only = True
                    messages.append(repair_message(calls, str(exc)))
                    continue
                results = []
                for call in calls:
                    tool_started = time.monotonic()
                    result = await tools.execute(call)
                    events.append({"tool": call["name"],
                                   "elapsed_ms": round((time.monotonic() - tool_started) * 1000),
                                   "outcome": result.get("error", "ok"),
                                   "property_ids": [p["id"] for p in result.get("results", [])]})
                    results.append({"type": "tool_result", "tool_use_id": call["id"],
                                    "content": json.dumps(result, ensure_ascii=False)})
                messages.append({"role": "user", "content": results})
            else:
                raise RuntimeError("tool_round_limit")
    except Superseded:
        status = "superseded"
    except Exception as exc:
        status, error_code = "failed", type(exc).__name__
        logger.warning("conversation_error conversation=%s error=%s", conversation_id, error_code)
        cards = []
        reply = recovery_reply([], tools.recovery_control)
        text = "\n\n".join(b.text for b in reply.blocks if b.kind == "text")
    finally:
        if owns_client and client is not None:
            await client.close()
    await sync_to_async(finish_turn)(
        conversation_id, turn, text, cards, status, usage,
        round((time.monotonic() - started) * 1000), events, error_code, reply=reply,
    )
