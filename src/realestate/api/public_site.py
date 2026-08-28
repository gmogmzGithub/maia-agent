"""Authenticated Product contracts consumed only by the separate public site."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import ChannelHandoffPurpose, PublicAnalyticsEventName
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
from realestate.domain.public.saved import SavedAction, SavedCommand, SavedCollections
from realestate.domain.public.website_conversation import (
    WebsiteCommand,
    WebsiteConversation,
)

router = APIRouter(prefix="/internal/public-site", tags=["public-site-internal"])


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


def _authorize(request: Request) -> None:
    expected = request.app.state.settings.site_internal_token
    supplied = request.headers.get("Authorization", "")
    wanted = f"Bearer {expected}" if expected else ""
    if not wanted or not hmac.compare_digest(supplied, wanted):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


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
    _authorize(request)
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
                at=datetime.now(tz=UTC),
            )
            return _json(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/listings/{slug}")
async def listing(request: Request, slug: str) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await PublicListing(session, await _actor(session)).read(
                slug, at=datetime.now(tz=UTC)
            )
            return _json(result, status_code=result.status_code)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/media/{media_id}")
async def media(request: Request, media_id: uuid.UUID) -> Response:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await PublicListing(session, await _actor(session)).media(
                media_id, at=datetime.now(tz=UTC)
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
    _authorize(request)
    async with request.app.state.database.session_scope() as session:
        result = await SavedCollections(session, await _actor(session)).read(
            token, at=datetime.now(tz=UTC)
        )
        return _json(result)


@router.post("/saved")
async def mutate_saved(
    request: Request,
    body: SavedBody,
    token: str | None = Header(default=None, alias="X-Collection-Token"),
) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await SavedCollections(session, await _actor(session)).record(
                SavedCommand(
                    action=body.action,
                    command_key=body.command_key,
                    collection_token=token,
                    listing_id=body.listing_id,
                ),
                at=datetime.now(tz=UTC),
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/shared/{token}")
async def shared(request: Request, token: str) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await SavedCollections(session, await _actor(session)).shared(
                token, at=datetime.now(tz=UTC)
            )
            return _json(result)
    except NotFound as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.get("/conversation")
async def conversation(
    request: Request,
    token: str | None = Header(default=None, alias="X-Conversation-Token"),
) -> JSONResponse:
    _authorize(request)
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
        conversation_id, messages = await module.read(token, at=datetime.now(tz=UTC))
        await session.commit()
        return _json({"conversation_id": conversation_id, "messages": messages})


@router.post("/conversation")
async def converse(
    request: Request,
    body: ConversationBody,
    token: str | None = Header(default=None, alias="X-Conversation-Token"),
) -> JSONResponse:
    _authorize(request)
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
                at=datetime.now(tz=UTC),
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/handoffs")
async def handoff(request: Request, body: HandoffBody) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await ChannelHandoff(session, await _actor(session)).create(
                CreateHandoff(**body.model_dump()), at=datetime.now(tz=UTC)
            )
            await session.commit()
            return _json(result)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/events", status_code=202)
async def event(request: Request, body: EventBody) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            recorded = await PublicAnalytics(session, await _actor(session)).record(
                PublicEventCommand(**body.model_dump())
            )
            await session.commit()
            return _json({"recorded": recorded}, status_code=202)
    except (ValueError, CommercialError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/discovery/{listing_id}")
async def discovery(request: Request, listing_id: uuid.UUID) -> JSONResponse:
    _authorize(request)
    try:
        async with request.app.state.database.session_scope() as session:
            result = await DiscoveryPublication(session, await _actor(session)).project(
                listing_id, at=datetime.now(tz=UTC)
            )
            return _json(result, status_code=result.status_code)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
