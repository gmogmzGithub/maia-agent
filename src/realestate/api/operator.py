"""Plumbing every operator surface needs, spelled once.

Resolving who is asking, wrapping a page in the shared shell, minting and
validating an idempotency key, and turning a domain refusal into a page an
operator can read. None of it is policy — the modules below hold that — but all
of it is the kind of thing that goes subtly wrong when each router keeps its own
copy.

It lives in its own module rather than on one of the routers because Stage 3
added a second and third: the CRM pipeline, the team surfaces, and the visit
Calendar all need the same five helpers, and importing them from whichever
router happened to define them first is how one of them ends up with a slightly
different authorization check.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from realestate.api.developer import require_developer
from realestate.api.ui import escape, layout
from realestate.db.models import MemberRole
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    NotAuthorized,
    UnknownMember,
)
from realestate.domain.commercial.organization import (
    ROLE_LABELS,
    OrganizationDirectory,
)
from realestate.domain.internal_alerts import InternalAlerts


async def require_actor(
    request: Request, login: str = Depends(require_developer)
) -> Actor:
    """Resolve the authenticated credential to an Organization member.

    Authentication is unchanged; this is the authorization step Stage 2 added. A
    credential that is valid but unknown to the Organization is refused with an
    explanation an operator can act on, rather than silently granted the
    authority the surface happens to expose.
    """
    async with request.app.state.database.session_scope() as session:
        try:
            actor = await OrganizationDirectory(session).resolve_actor(login)
            actor = replace(
                actor,
                alert_count=await InternalAlerts(session).open_count(actor),
            )
            if actor.read_only and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                actor.require_writable()
            return actor
        except UnknownMember as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=exc.message
            ) from exc
        except NotAuthorized as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=exc.message
            ) from exc


async def require_administrator(actor: Actor = Depends(require_actor)) -> Actor:
    """An Actor that administers the Organization, or a refusal.

    Property management, Advisor access, absences and assignment are the
    Organization Administrator's authority (CONTEXT.md).
    """
    if not actor.is_administrator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Sólo un administrador de la organización puede administrar el "
                "inventario."
            ),
        )
    return actor


def shell(actor: Actor, title: str, content: str, *, active: str) -> HTMLResponse:
    """One page, in the shared Mexican Spanish shell."""
    return layout(
        title,
        content,
        active=active,
        actor_label=actor.display_name,
        role_label=(
            ROLE_LABELS[MemberRole.ADMINISTRATOR.value]
            if actor.is_administrator
            else ROLE_LABELS[MemberRole.ADVISOR.value]
        ),
        organization_label=actor.organization_name,
        is_administrator=actor.is_administrator,
        read_only=actor.read_only,
        support_expires_at=actor.support_expires_at,
        support_reason=actor.support_reason,
        alert_count=actor.alert_count,
    )


def command_field() -> str:
    """A hidden idempotency key, minted when the form is rendered.

    Without it every submission invents its own key, so the domain's
    idempotency is real but unreachable: a double-submitted button produces two
    records. Minted per render rather than per request, so re-submitting *the
    page in front of the operator* — the double click, the impatient refresh,
    the flaky-connection retry — replays instead of repeating.
    """
    return f'<input type="hidden" name="clave" value="{uuid.uuid4().hex}">'


def command_key(form: Mapping[str, Any], prefix: str) -> str:
    """The command key for one submission.

    A mutation without one is refused: silently minting a server-side value
    makes a retry look protected while guaranteeing that it runs twice.
    """
    nonce = str(form.get("clave", "")).strip()
    if not nonce:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Falta la clave de operación; recarga la página e inténtalo de "
                "nuevo."
            ),
        )
    return f"{prefix}:{nonce}"


def command_payload(form: Mapping[str, Any]) -> dict[str, str]:
    """Stable request facts bound to an idempotency key, excluding the key."""
    return {
        str(name): str(value) for name, value in form.items() if str(name) != "clave"
    }


def tag(text: str, kind: str = "") -> str:
    classes = f"tag {kind}".strip()
    return f'<span class="{escape(classes)}">{escape(text)}</span>'


def refusal(actor: Actor, exc: CommercialError, *, active: str) -> HTMLResponse:
    """A domain refusal as a page, in the operator's language.

    Returned rather than raised so the operator keeps the navigation and can act
    on the sentence instead of reading a bare status code.

    The status is deliberately uniform. ``NotFound`` already covers "exists but
    is not yours" — telling an Advisor that an Opportunity exists and belongs to
    somebody else discloses the pipeline — and answering a refused
    Administrator-only surface differently would let a caller distinguish the
    two by status alone.
    """
    response = shell(
        actor,
        "No disponible",
        f'<div class="error" role="alert">{escape(exc.message)}</div>'
        '<p><a href="/crm">Volver al panel</a></p>',
        active=active,
    )
    response.status_code = status.HTTP_404_NOT_FOUND
    return response


def redirect_back(
    path: str, *, saved: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Return to a surface carrying one outcome. The only redirect builder.

    ``303`` so the browser re-issues the follow-up as a GET, which is what makes
    a refresh after a mutation harmless. The message is percent-encoded here
    rather than at each call site: one that forgot would break on any Spanish
    text containing ``&``.
    """
    query = f"?guardado={quote(saved)}" if saved else ""
    if error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"{path}{query}", status_code=303)


def form_uuid(value: object) -> uuid.UUID | None:
    """A UUID from a form field, or ``None`` when the field cannot supply one.

    ``None`` rather than an exception because every caller answers a malformed
    id with its own Spanish sentence next to the field it came from — "elige un
    asesor" and "no encontramos esa solicitud" are different remedies.
    """
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
