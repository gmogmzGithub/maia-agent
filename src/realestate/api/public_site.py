"""Authenticated Product contracts consumed only by the separate public site."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.clock import utc_now
from realestate.db.models import (
    ChannelHandoffPurpose,
    PublicAnalyticsEventName,
    SponsoredSurface,
)
from realestate.domain.catalog.storage import MediaStorageError
from realestate.domain.commercial.actors import Actor, CommercialError, NotFound
from realestate.domain.commercial.organization import OrganizationDirectory
from realestate.domain.public.analytics import PublicAnalytics, PublicEventCommand
from realestate.domain.public.catalog import PublicCatalog, SearchQuery
from realestate.domain.public.discovery import DiscoveryPublication
from realestate.domain.public.handoff import (
    ChannelHandoff,
    CreateHandoff,
)
from realestate.domain.public.listing import PublicListing
from realestate.domain.public.responders import HermesWebsiteResponder
from realestate.domain.public.measurement import (
    GalleryDepth,
    ListingOpen,
    PublicMeasurement,
)
from realestate.domain.public.saved import SavedAction, SavedCommand, SavedCollections
from realestate.domain.public.sponsored import PublicSponsored
from realestate.domain.sponsorship.sharing import (
    ShareUnavailable,
    SponsorshipSharing,
    report_lines,
    report_pdf,
)
from realestate.domain.public.website_conversation import (
    WebsiteCommand,
    WebsiteConversation,
)

def require_site_token(request: Request) -> None:
    """Every route on this router is site-only, so the guard hangs off the router.

    Declared once rather than called per handler: this surface exposes the whole
    public catalog, saved collections, conversations and handoff minting, and a
    twelfth route added without the call would be unauthenticated by omission.
    """
    expected = request.app.state.settings.site_internal_token
    supplied = request.headers.get("Authorization", "")
    wanted = f"Bearer {expected}" if expected else ""
    if not wanted or not hmac.compare_digest(supplied, wanted):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


router = APIRouter(
    prefix="/internal/public-site",
    tags=["public-site-internal"],
    dependencies=[Depends(require_site_token)],
)


class SavedBody(BaseModel):
    action: SavedAction
    command_key: str = Field(min_length=8, max_length=200)
    listing_id: uuid.UUID | None = None


class ConversationBody(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)
    listing_ids: tuple[uuid.UUID, ...] = ()


class HandoffBody(BaseModel):
    purpose: ChannelHandoffPurpose
    command_key: str = Field(min_length=8, max_length=200)
    website_conversation_id: uuid.UUID | None = None
    saved_collection_id: uuid.UUID | None = None
    listing_id: uuid.UUID | None = None


class EventBody(BaseModel):
    event_key: str = Field(min_length=8, max_length=200)
    name: PublicAnalyticsEventName
    surface: str = Field(min_length=1, max_length=40)
    listing_id: uuid.UUID | None = None
    properties: dict[str, str | int | bool] = Field(default_factory=dict)
    occurred_at: datetime


class ListingOpenBody(BaseModel):
    event_key: str = Field(min_length=8, max_length=200)
    listing_id: uuid.UUID
    surface: str = Field(min_length=1, max_length=20)
    occurred_at: datetime


class GalleryDepthBody(BaseModel):
    """Raw gallery depth. The milestone is Product's decision, not the page's."""

    event_key: str = Field(min_length=8, max_length=200)
    listing_id: uuid.UUID
    photographs: int = Field(ge=0, le=500)
    gallery_fraction: float = Field(ge=0, le=1)
    occurred_at: datetime


class VisibleImpressionBody(BaseModel):
    """One browser-reported visibility observation for a paid placement.

    The fraction and the duration are reported, never the verdict: Product
    applies the versioned threshold itself, so a page cannot claim a Visible
    Impression it did not earn.
    """

    campaign_id: uuid.UUID
    listing_id: uuid.UUID
    surface: str = Field(min_length=1, max_length=20)
    visible_fraction: float = Field(ge=0, le=1)
    continuous_milliseconds: int = Field(ge=0, le=600_000)
    occurred_at: datetime


async def _actor(session: AsyncSession) -> Actor:
    organization_id = await OrganizationDirectory(session).organization_id()
    return Actor.product(organization_id, "PublicSite")


def _json(value: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder(value), status_code=status_code)


def _decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise HTTPException(status_code=422, detail="El precio no es válido.") from exc


@router.get("/catalog")
async def catalog(
    request: Request,
    operation: str | None = None,
    zone: str | None = None,
    property_type: str | None = None,
    minimum_price: str | None = None,
    maximum_price: str | None = None,
    sort: str = "relevance",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=24),
) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await PublicCatalog(session, await _actor(session)).search(
                SearchQuery(
                    operation=operation,
                    zone=zone,
                    property_type=property_type,
                    minimum_price=_decimal(minimum_price),
                    maximum_price=_decimal(maximum_price),
                    sort=sort,
                    page=page,
                    page_size=page_size,
                ),
                at=utc_now(),
            )
            return _json(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/listings/{slug}")
async def listing(request: Request, slug: str) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await PublicListing(session, await _actor(session)).read(
                slug, at=utc_now()
            )
            return _json(result, status_code=result.status_code)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/media/{media_id}")
async def media(request: Request, media_id: uuid.UUID) -> Response:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await PublicListing(session, await _actor(session)).media(
                media_id, at=utc_now()
            )
        content = await request.app.state.media_storage.read(result.storage_key)
    except (NotFound, MediaStorageError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content,
        media_type=result.content_type,
        headers={
            "Cache-Control": "public, max-age=3600, must-revalidate",
            "ETag": f'"{result.checksum}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/saved")
async def saved(
    request: Request,
    token: str | None = Header(default=None, alias="X-Collection-Token"),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        result = await SavedCollections(session, await _actor(session)).read(
            token, at=utc_now()
        )
        return _json(result)


@router.post("/saved")
async def mutate_saved(
    request: Request,
    body: SavedBody,
    token: str | None = Header(default=None, alias="X-Collection-Token"),
) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await SavedCollections(session, await _actor(session)).record(
                SavedCommand(
                    action=body.action,
                    command_key=body.command_key,
                    collection_token=token,
                    listing_id=body.listing_id,
                ),
                at=utc_now(),
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/shared/{token}")
async def shared(request: Request, token: str) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await SavedCollections(session, await _actor(session)).shared(
                token, at=utc_now()
            )
            return _json(result)
    except NotFound as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.get("/conversation")
async def conversation(
    request: Request,
    token: str | None = Header(default=None, alias="X-Conversation-Token"),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        module = WebsiteConversation(
            session,
            await _actor(session),
            HermesWebsiteResponder(
                request.app.state.database,
                request.app.state.hermes,
                request.app.state.settings.sales_profile,
            ),
        )
        conversation_id, messages = await module.read(token, at=utc_now())
        await session.commit()
        return _json({"conversation_id": conversation_id, "messages": messages})


@router.post("/conversation")
async def converse(
    request: Request,
    body: ConversationBody,
    token: str | None = Header(default=None, alias="X-Conversation-Token"),
) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await WebsiteConversation(
                session,
                await _actor(session),
                HermesWebsiteResponder(
                    request.app.state.database,
                    request.app.state.hermes,
                    request.app.state.settings.sales_profile,
                ),
            ).handle(
                WebsiteCommand(
                    message=body.message,
                    command_key=body.command_key,
                    conversation_token=token,
                    listing_ids=body.listing_ids,
                ),
                at=utc_now(),
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/handoffs")
async def handoff(request: Request, body: HandoffBody) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await ChannelHandoff(session, await _actor(session)).create(
                CreateHandoff(**body.model_dump()), at=utc_now()
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/events", status_code=202)
async def event(request: Request, body: EventBody) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            session_value, bot, internal = _measurement_context(request)
            recorded = await PublicAnalytics(session, await _actor(session)).record(
                PublicEventCommand(
                    **body.model_dump(),
                    session_value=session_value,
                    bot=bot,
                    internal=internal,
                )
            )
            await session.commit()
            return _json({"recorded": recorded}, status_code=202)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _measurement_context(request: Request) -> tuple[str, bool, bool]:
    """The session reference and the two exclusion flags, from headers only.

    The site inspects the user agent and sends a boolean; the raw string never
    reaches Product, so no analytics row can hold one. ``X-Internal-Preview`` is
    how an operator looks at a surface without consuming a buyer's cap.
    """
    session_value = request.headers.get("X-Session-Reference", "").strip()[:120]
    bot = request.headers.get("X-Crawler", "").strip().casefold() == "true"
    internal = (
        request.headers.get("X-Internal-Preview", "").strip().casefold() == "true"
    )
    return session_value, bot, internal


@router.get("/sponsored")
async def sponsored(
    request: Request,
    surface: str = Query(min_length=1, max_length=20),
    visible_results: int = Query(default=0, ge=0, le=200),
    organic: str = "",
) -> JSONResponse:
    """The labelled paid section for one surface.

    Returned as its own list, never merged into the organic results. The caller
    receives the slots and renders them in their dedicated positions; the
    organic ordering it already has is not touched by this call.
    """
    if surface not in {item.value for item in SponsoredSurface}:
        raise HTTPException(status_code=422, detail="La superficie no es válida.")
    try:
        organic_ids = tuple(
            uuid.UUID(value) for value in organic.split(",") if value.strip()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="La lista de resultados orgánicos no es válida."
        ) from exc
    session_value, bot, internal = _measurement_context(request)
    async with request.app.state.database.session_scope() as session:
        result = await PublicSponsored(session, await _actor(session)).for_surface(
            surface=surface,
            at=utc_now(),
            visible_results=visible_results,
            organic_listing_ids=organic_ids,
            session_value=session_value,
            bot=bot,
            internal=internal,
        )
        await session.commit()
        return _json(result)


@router.post("/sponsored/visible", status_code=202)
async def visible_impression(
    request: Request, body: VisibleImpressionBody
) -> JSONResponse:
    session_value, bot, internal = _measurement_context(request)
    try:
        async with request.app.state.database.session_scope() as session:
            counted = await PublicSponsored(
                session, await _actor(session)
            ).count_visible(
                campaign_id=body.campaign_id,
                listing_id=body.listing_id,
                surface=body.surface,
                visible_fraction=body.visible_fraction,
                continuous_milliseconds=body.continuous_milliseconds,
                session_value=session_value,
                at=body.occurred_at,
                bot=bot,
                internal=internal,
            )
            await session.commit()
            return _json({"counted": counted}, status_code=202)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/measurement/listing-open", status_code=202)
async def listing_open(request: Request, body: ListingOpenBody) -> JSONResponse:
    session_value, bot, internal = _measurement_context(request)
    try:
        async with request.app.state.database.session_scope() as session:
            recorded = await PublicMeasurement(
                session, await _actor(session)
            ).listing_open(
                ListingOpen(
                    **body.model_dump(),
                    session_value=session_value,
                    bot=bot,
                    internal=internal,
                )
            )
            await session.commit()
            return _json({"recorded": recorded}, status_code=202)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/measurement/gallery-depth", status_code=202)
async def gallery_depth(request: Request, body: GalleryDepthBody) -> JSONResponse:
    session_value, bot, internal = _measurement_context(request)
    try:
        async with request.app.state.database.session_scope() as session:
            outcome = await PublicMeasurement(
                session, await _actor(session)
            ).gallery_depth(
                GalleryDepth(
                    **body.model_dump(),
                    session_value=session_value,
                    bot=bot,
                    internal=internal,
                )
            )
            await session.commit()
            return _json(outcome, status_code=202)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sponsorship-report/{token}")
async def sponsorship_report(request: Request, token: str) -> JSONResponse:
    """The buyer report behind one expiring link, as aggregate lines.

    Rendered to the same lines the PDF uses rather than to the report object:
    the buyer surface must not be able to grow a field by somebody adding one to
    the dataclass.
    """
    try:
        async with request.app.state.database.session_scope() as session:
            report = await SponsorshipSharing(session, await _actor(session)).resolve(
                token, at=utc_now()
            )
            await session.commit()
            return _json(
                {
                    "label": report.label,
                    "listing_title": report.listing_title,
                    "period_start": report.period_start,
                    "period_end": report.period_end,
                    "definition_version": report.definition_version,
                    "lines": [
                        {"text": line.text, "style": str(line.style)}
                        for line in report_lines(report)
                    ],
                }
            )
    except ShareUnavailable as exc:
        raise HTTPException(status_code=410, detail=exc.message) from exc


@router.get("/sponsorship-report/{token}/pdf")
async def sponsorship_report_pdf(request: Request, token: str) -> Response:
    try:
        async with request.app.state.database.session_scope() as session:
            report = await SponsorshipSharing(session, await _actor(session)).resolve(
                token, at=utc_now()
            )
            content = report_pdf(report)
            await session.commit()
    except ShareUnavailable as exc:
        raise HTTPException(status_code=410, detail=exc.message) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="reporte-patrocinada.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/discovery/{listing_id}")
async def discovery(request: Request, listing_id: uuid.UUID) -> JSONResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await DiscoveryPublication(session, await _actor(session)).project(
                listing_id, at=utc_now()
            )
            return _json(result, status_code=result.status_code)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
