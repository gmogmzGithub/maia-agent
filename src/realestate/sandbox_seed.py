"""Explicit, local-only synthetic data for a complete Maia walkthrough.

The public site never reads this module. Running it submits the same commands
as the administrative and inbound surfaces, so PostgreSQL remains the only
inventory and CRM truth used by the demo.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.channels.whatsapp.payload import InboundMessage
from realestate.domain.scheduling.calendars import GoogleCalendarDirectory
from realestate.config import Settings, get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    ApprovedMessageTemplate,
    Appointment,
    AppointmentStatus,
    CatalogListing,
    CatalogPresentationTier,
    ChannelBindingKind,
    ChannelBindingState,
    CollectionState,
    ConsentCategory,
    Conversation,
    Development,
    DevelopmentCampaign,
    FactsReviewState,
    InboxMessage,
    InboxStatus,
    ListingAuthority,
    ListingMedia,
    ListingPublicationState,
    Lead,
    MessageTemplateStatus,
    NextAction,
    NextActionKind,
    Opportunity,
    OpportunityAssignment,
    OpportunityOrigin,
    OpportunityStage,
    OutboundInitiation,
    OutboxMessage,
    OutboxStatus,
    Organization,
    OrganizationChannelBinding,
    OrganizationMember,
    PriceCatalogStatus,
    ReactivationCandidate,
    SponsorshipCampaign,
    SponsorshipReportLink,
)
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.availability import WeeklySchedule
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateDevelopment,
    ReviewDevelopmentFacts,
    ReviewListingFacts,
    SetPublicationState,
    SetReadinessOverride,
)
from realestate.domain.catalog.media import AddMedia, MediaAdministration
from realestate.domain.catalog.storage import MediaStorage, MediaStorageError
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.actors import Actor
from realestate.domain.commercial.intake import CommercialIntake
from realestate.domain.commercial.needs import (
    ECONOMIC_RANGE,
    ESSENTIAL_REQUIREMENTS,
    HORIZON,
    INTENT,
    SERVICE_AREA,
    CriterionStatement,
    PropertyNeeds,
)
from realestate.domain.commercial.next_actions import NextActions, ScheduleNextAction
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    DormantReason,
    OpportunityManagement,
    QualificationAction,
    RecordDormant,
    RecordLost,
    RecordWon,
    LostReason,
    WonEvidence,
)
from realestate.domain.commercial.organization import OrganizationDirectory
from realestate.domain.engagement.campaigns import Campaigns, PlanCampaign
from realestate.domain.engagement.reactivation import Reactivation
from realestate.domain.engagement.templates import TemplateRegistry
from realestate.domain.inbox import InboxService
from realestate.domain.outbound import (
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    Queued,
)
from realestate.domain.outbox import OutboxService
from realestate.domain.platform.credentials import SecretResolver
from realestate.domain.platform.whatsapp import OrganizationMetaTemplateSources
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.domain.property_document import SCHEMA_VERSION, render_property_document
from realestate.domain.scheduling.advisors import (
    AdvisorScheduling,
    SlotQuery,
    SlotsUnavailable,
)
from realestate.domain.scheduling.appointments import (
    Appointments,
    BookVisit,
    VisitRefused,
)
from realestate.domain.sponsorship.campaigns import (
    OpenCampaign,
    RecordCollection,
    ScheduleCampaign,
    SponsorshipCampaigns,
)
from realestate.infrastructure.media_storage import media_storage_from_settings
from realestate.domain.sponsorship.pricing import (
    DraftCatalog,
    PriceLine,
    PublishCatalog,
    SponsorshipPricing,
)
from realestate.domain.sponsorship.quoting import (
    AcceptQuote,
    QuoteCommand,
    SponsorshipQuoting,
)
from realestate.domain.sponsorship.sharing import SponsorshipSharing


@dataclass(frozen=True)
class PropertySeed:
    key: str
    name: str
    property_type: str
    operation: str
    price: int
    city: str
    neighborhood: str
    bedrooms: int
    bathrooms: int
    construction_m2: int
    description: str


PROPERTY_SEEDS = (
    PropertySeed(
        "casa-nispero",
        "Casa Níspero",
        "House",
        "Sale",
        3_850_000,
        "Zapopan",
        "Valle Imperial",
        3,
        2,
        164,
        "Casa luminosa con jardín privado y espacios pensados para la vida familiar.",
    ),
    PropertySeed(
        "loft-americana",
        "Loft Americana",
        "Apartment",
        "Rental",
        29_500,
        "Guadalajara",
        "Americana",
        2,
        2,
        108,
        "Loft contemporáneo cerca de corredores culturales, restaurantes y servicios.",
    ),
    PropertySeed(
        "casa-patio",
        "Casa Patio",
        "House",
        "Sale",
        5_700_000,
        "Tlaquepaque",
        "Centro",
        3,
        3,
        212,
        "Casa de distribución abierta alrededor de un patio central arbolado.",
    ),
    PropertySeed(
        "residencia-olivo",
        "Residencia Olivo",
        "House",
        "Sale",
        9_800_000,
        "Zapopan",
        "Puerta de Hierro",
        4,
        4,
        338,
        "Residencia amplia con estudio, terraza y áreas sociales conectadas al jardín.",
    ),
    PropertySeed(
        "departamento-nube",
        "Departamento Nube",
        "Apartment",
        "Sale",
        12_400_000,
        "Zapopan",
        "Valle Real",
        3,
        3,
        245,
        "Departamento de altura con vistas abiertas, elevador y amenidades compartidas.",
    ),
    PropertySeed(
        "casa-barranca",
        "Casa Barranca",
        "House",
        "Sale",
        15_900_000,
        "Guadalajara",
        "Huentitán",
        4,
        5,
        420,
        "Casa de arquitectura sobria con terrazas orientadas hacia la barranca.",
    ),
    PropertySeed(
        "casa-loma-alta",
        "Casa Loma Alta",
        "House",
        "Sale",
        24_500_000,
        "Zapopan",
        "Las Cañadas",
        4,
        6,
        610,
        "Residencia de gran formato con alberca, jardín y espacios para recibir.",
    ),
    PropertySeed(
        "penthouse-colomos",
        "Penthouse Colomos",
        "Apartment",
        "Sale",
        31_800_000,
        "Guadalajara",
        "Colomos Providencia",
        4,
        5,
        520,
        "Penthouse con terrazas privadas, vistas arboladas y elevador de acceso directo.",
    ),
    PropertySeed(
        "residencia-canada",
        "Residencia Cañada",
        "House",
        "Sale",
        46_000_000,
        "Zapopan",
        "Las Cañadas",
        5,
        7,
        890,
        "Residencia de autor con áreas de convivencia, jardín maduro y máxima privacidad.",
    ),
)

EXTERIOR_IMAGES = (
    "abby-rurenko-uOYak90r4L0-unsplash.jpg",
    "brian-babb-XbwHrt87mQ0-unsplash.jpg",
    "frames-for-your-heart-2d4lAQAlbDA-unsplash.jpg",
    "frames-for-your-heart-mR1CIDduGLc-unsplash.jpg",
    "johnson-U6Q6zVDgmSs-unsplash.jpg",
    "phil-hearing-IYfp2Ixe9nM-unsplash.jpg",
    "redd-francisco-sejLyCD2UQE-unsplash.jpg",
    "scott-webb-1ddol8rgUH8-unsplash.jpg",
    "todd-kent-178j8tJrNlc-unsplash.jpg",
    "vu-anh-TiVPTYCG_3E-unsplash.jpg",
    "webaliser-_TPTXZd9mOo-unsplash.jpg",
    "wes-fischer-g39p1kDjvSY-unsplash.jpg",
    "zac-gudakov-wwqZ8CM21gg-unsplash.jpg",
)
INTERIOR_IMAGES = (
    "generated-interior-living.jpg",
    "generated-interior-kitchen.jpg",
)

SPONSORSHIP_CATALOG_VERSION = "sandbox-pilot-v1"
SPONSORSHIP_BUYER_LABEL = "Propietario sintético · Casa Níspero"
DEVELOPMENT_KEY = "sandbox-parque-norte"
DEVELOPMENT_CAMPAIGN_NAME = "Sandbox · Lanzamiento Parque Norte"


@dataclass(frozen=True)
class CrmSeed:
    key: str
    name: str
    wa_id: str
    message: str
    target: OpportunityStage
    intent: str
    area: str
    budget: str
    horizon: str
    requirements: str
    action_kind: NextActionKind | None = None
    action_due_days: int = 1
    release_assignment: bool = False
    progress_message: str | None = None
    reply: str | None = None

    @property
    def inbound_messages(self) -> tuple[str, ...]:
        """A short but causal synthetic conversation, in arrival order."""
        return (self.message,) + (
            (self.progress_message,) if self.progress_message else ()
        )


CRM_SEEDS = (
    CrmSeed(
        "conversation",
        "Demo · Alejandra Soto",
        "5210000000001",
        (
            "Quiero comprar una casa en Zapopan de 3.5 a 4.2 millones, en unos "
            "3 a 6 meses. Necesito 3 recámaras y jardín; me interesa Casa Níspero."
        ),
        OpportunityStage.IN_CONVERSATION,
        "Buy",
        "Zapopan",
        "3.5 a 4.2 millones MXN",
        "3 a 6 meses",
        "3 recámaras y jardín",
        NextActionKind.CALL,
        -1,
    ),
    CrmSeed(
        "qualified",
        "Demo · Carlos Rivera",
        "5210000000002",
        (
            "Confirmo que busco comprar en Zapopan, entre 9 y 11 millones, dentro "
            "de 3 meses. Necesito 4 recámaras, estudio y seguridad."
        ),
        OpportunityStage.QUALIFIED,
        "Buy",
        "Zapopan",
        "9 a 11 millones MXN",
        "Dentro de 3 meses",
        "4 recámaras, estudio y seguridad",
        NextActionKind.SEND_LISTINGS,
        1,
        reply=(
            "Perfecto, Carlos. Ya tengo clara tu búsqueda y un asesor continuará "
            "con una selección adecuada."
        ),
    ),
    CrmSeed(
        "searching",
        "Demo · Fernanda Luna",
        "5210000000003",
        (
            "Busco comprar un departamento cerca de Colomos, Guadalajara, de 12 "
            "a 18 millones, en 1 o 2 meses. Quiero 3 recámaras, elevador y terraza."
        ),
        OpportunityStage.SEARCHING,
        "Buy",
        "Guadalajara, zona Colomos",
        "12 a 18 millones MXN",
        "1 a 2 meses",
        "3 recámaras, elevador y terraza",
        NextActionKind.SEND_LISTINGS,
        2,
        reply=(
            "Gracias, Fernanda. Estamos revisando opciones que coincidan con esos "
            "criterios y te compartiremos una selección."
        ),
    ),
    CrmSeed(
        "visiting",
        "Demo · Diego Ortiz",
        "5210000000004",
        (
            "Quiero comprar en Tlaquepaque Centro este mes, con presupuesto de 5 a "
            "6.2 millones. Necesito 3 recámaras y patio."
        ),
        OpportunityStage.VISITING,
        "Buy",
        "Tlaquepaque Centro",
        "5 a 6.2 millones MXN",
        "Este mes",
        "3 recámaras y patio",
        NextActionKind.SCHEDULE_VISIT,
        1,
        progress_message="Casa Patio me gustó; quiero visitarla esta semana.",
        reply=(
            "Con gusto, Diego. Revisaremos los horarios disponibles para tu visita "
            "a Casa Patio."
        ),
    ),
    CrmSeed(
        "negotiating",
        "Demo · Mariana Torres",
        "5210000000005",
        (
            "Quiero comprar en Valle Real, Zapopan, de 11.5 a 12.5 millones, de "
            "inmediato. Busco 3 recámaras y amenidades."
        ),
        OpportunityStage.NEGOTIATING,
        "Buy",
        "Valle Real, Zapopan",
        "11.5 a 12.5 millones MXN",
        "Inmediato",
        "3 recámaras y amenidades",
        NextActionKind.DOCUMENT_REVIEW,
        1,
        progress_message="Me interesa presentar una propuesta por Departamento Nube.",
        reply=(
            "Gracias, Mariana. El asesor revisará contigo la propuesta y la "
            "documentación necesaria."
        ),
    ),
    CrmSeed(
        "dormant",
        "Demo · Javier Mendoza",
        "5210000000006",
        (
            "Quiero comprar en Las Cañadas, Zapopan, entre 22 y 26 millones, en 6 "
            "a 9 meses. Necesito 4 recámaras, jardín y alberca."
        ),
        OpportunityStage.DORMANT,
        "Buy",
        "Las Cañadas, Zapopan",
        "22 a 26 millones MXN",
        "6 a 9 meses",
        "4 recámaras, jardín y alberca",
        progress_message=(
            "Me gusta Casa Loma Alta, pero debo esperar la autorización de mi crédito."
        ),
        reply=(
            "Entendido, Javier. Dejamos la búsqueda en pausa y la retomamos cuando "
            "tu banco confirme el crédito."
        ),
    ),
    CrmSeed(
        "lost",
        "Demo · Sofía Campos",
        "5210000000007",
        (
            "Busco comprar en Guadalajara, entre 4 y 6 millones, este trimestre. "
            "Necesito al menos 3 recámaras."
        ),
        OpportunityStage.LOST,
        "Buy",
        "Guadalajara",
        "4 a 6 millones MXN",
        "Concluido",
        "3 recámaras",
        progress_message="Gracias por la atención; finalmente compré otra propiedad.",
        reply="Gracias por avisarnos, Sofía. Cerramos esta búsqueda.",
    ),
    CrmSeed(
        "won",
        "Demo · Andrés Navarro",
        "5210000000008",
        (
            "Busco rentar en la Americana, Guadalajara, por 25 a 32 mil pesos al "
            "mes, de inmediato. Necesito 2 recámaras y estacionamiento."
        ),
        OpportunityStage.WON,
        "Rent",
        "Americana, Guadalajara",
        "25000 a 32000 MXN mensuales",
        "Inmediato",
        "2 recámaras y estacionamiento",
        progress_message=(
            "Confirmo que firmamos el contrato de renta del Loft Americana."
        ),
        reply="Excelente, Andrés. Quedó registrado el cierre de la operación.",
    ),
    CrmSeed(
        "assignment-queue",
        "Demo · Paula Jiménez",
        "5210000000009",
        (
            "Quiero comprar una residencia en Zapopan, entre 14 y 18 millones, en "
            "2 a 4 meses. Necesito 4 recámaras y estudio."
        ),
        OpportunityStage.QUALIFIED,
        "Buy",
        "Zapopan",
        "14 a 18 millones MXN",
        "2 a 4 meses",
        "4 recámaras y estudio",
        release_assignment=True,
    ),
)


def require_local_sandbox(settings: Settings, *, confirmed: bool) -> None:
    """Refuse synthetic writes unless the operator named a loopback runtime."""
    if not confirmed:
        raise RuntimeError("Falta --confirm-local-sandbox; no se escribió nada.")
    site_host = (urlparse(settings.site_public_origin).hostname or "").casefold()
    database_host = (make_url(settings.database_url).host or "").casefold()
    if site_host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("El sitio no usa un origen local; se rechazó la carga.")
    if database_host not in {"db", "localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("PostgreSQL no es local; se rechazó la carga.")


def _property_document(seed: PropertySeed) -> bytes:
    return render_property_document(
        {
            "schema_version": SCHEMA_VERSION,
            "property_id": seed.key,
            "name": seed.name,
            "property_type": seed.property_type,
            "operation": seed.operation,
            "price_amount": seed.price,
            "price_currency": "MXN",
            "state": "Jalisco",
            "city": seed.city,
            "neighborhood": seed.neighborhood,
            "public_location_notes": "Ubicación aproximada; la dirección se confirma al agendar.",
            "bedrooms": seed.bedrooms,
            "full_bathrooms": seed.bathrooms,
            "half_bathrooms": 1,
            "parking_spaces": max(1, seed.bedrooms - 1),
            "construction_m2": seed.construction_m2,
            "land_m2": round(seed.construction_m2 * 1.35),
            "maintenance_status": "Unknown",
            "in_development": True,
            "private_characteristics": [
                "Jardín privado",
                "Estacionamiento techado",
            ],
            "community_amenities": ["Seguridad 24 horas", "Jardines comunes"],
        },
        general_description=seed.description,
        distribution=(
            f"{seed.bedrooms} recámaras, {seed.bathrooms} baños completos y "
            "áreas sociales conectadas. La distribución y las medidas fueron "
            "revisadas para esta carga sintética."
        ),
    )


async def _seed_inventory(
    session: AsyncSession,
    actor: Actor,
    settings: Settings,
    storage: MediaStorage,
) -> tuple[int, int]:
    artifacts = ArtifactStore(Path(settings.artifact_root))
    asset_root = Path(__file__).parents[2] / "bootstrap/sandbox/listing-media"
    created = 0
    published = 0
    for index, seed in enumerate(PROPERTY_SEEDS):
        listing = await session.scalar(
            select(CatalogListing).where(
                CatalogListing.organization_id == actor.organization_id,
                CatalogListing.listing_key == f"{seed.key}-legacy",
            )
        )
        if listing is None:
            accepted = await PropertyService(
                session,
                artifacts,
                organization_id=actor.organization_id,
            ).accept_upload(
                f"{seed.key}.md",
                _property_document(seed),
                actor.label,
                actor_type=actor.actor_type,
                create_only=True,
                visit_address=(
                    f"Dirección sintética de demostración, {seed.neighborhood}, "
                    f"{seed.city}, Jalisco"
                ),
            )
            created += int(accepted.created)
            listing = await session.scalar(
                select(CatalogListing).where(
                    CatalogListing.organization_id == actor.organization_id,
                    CatalogListing.listing_key == f"{seed.key}-legacy",
                )
            )
        if listing is None:
            raise RuntimeError(f"No se creó la publicación de {seed.name}.")

        await CatalogAdministration(session).record(
            actor,
            ReviewListingFacts(
                listing_id=listing.id,
                review_state=FactsReviewState.APPROVED,
                facts={**dict(listing.facts), "description": seed.description},
                command_key=(f"sandbox-listing-facts:{seed.key}:{listing.id}:v2"),
            ),
        )
        await session.commit()

        all_images = EXTERIOR_IMAGES + INTERIOR_IMAGES
        cover = EXTERIOR_IMAGES[index]
        interior = INTERIOR_IMAGES[index % len(INTERIOR_IMAGES)]
        rotated = all_images[index:] + all_images[:index]
        extras = tuple(
            filename for filename in rotated if filename not in {cover, interior}
        )[:10]
        image_names = (cover, interior, *extras)
        for order, filename in enumerate(image_names):
            source = asset_root / filename
            content = source.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            existing_media = await session.scalar(
                select(ListingMedia).where(
                    ListingMedia.organization_id == actor.organization_id,
                    ListingMedia.listing_id == listing.id,
                    ListingMedia.checksum == checksum,
                    ListingMedia.revoked_at.is_(None),
                )
            )
            if existing_media is not None:
                try:
                    stored = await storage.read(existing_media.storage_key)
                except MediaStorageError:
                    stored = None
                if stored is None or hashlib.sha256(stored).hexdigest() != checksum:
                    await storage.put(existing_media.storage_key, content)
                continue
            await MediaAdministration(session, storage).record(
                actor,
                AddMedia(
                    listing_id=listing.id,
                    original_filename=filename,
                    content_type="image/jpeg",
                    content=content,
                    provenance=(
                        "Fotografía sintética de sandbox con procedencia documentada "
                        "en bootstrap/sandbox/LISTING-MEDIA-PROVENANCE.md."
                    ),
                    authority=ListingAuthority.AUTHORIZED,
                    authority_evidence=(
                        "Licencia y procedencia revisadas para el conjunto sintético local."
                    ),
                    is_cover=order == 0,
                    sort_order=order,
                    space_group=(
                        "Fachada"
                        if order == 0
                        else "Interiores"
                        if order == 1
                        else "Amenidades"
                        if order >= 6
                        else "Propiedad"
                    ),
                    high_resolution=True,
                    cache_keys=(),
                    command_key=(f"sandbox-media:{seed.key}:{listing.id}:{order}:v2"),
                ),
            )

        if (
            listing.automatic_tier == CatalogPresentationTier.SUPER_PREMIUM.value
            and not listing.readiness_override
        ):
            await CatalogAdministration(session).record(
                actor,
                SetReadinessOverride(
                    listing_id=listing.id,
                    enabled=True,
                    command_key=(
                        f"sandbox-readiness-override:{seed.key}:{listing.id}:v2"
                    ),
                ),
            )
            await session.commit()

        if listing.publication_state != ListingPublicationState.PUBLISHED.value:
            await CatalogAdministration(session).record(
                actor,
                SetPublicationState(
                    listing_id=listing.id,
                    state=ListingPublicationState.PUBLISHED,
                    command_key=f"sandbox-publish:{seed.key}:{listing.id}:v2",
                ),
            )
            await session.commit()
            published += 1
    return created, published


def _criteria(seed: CrmSeed) -> tuple[CriterionStatement, ...]:
    values = (
        (INTENT, seed.intent),
        (SERVICE_AREA, seed.area),
        (ECONOMIC_RANGE, seed.budget),
        (HORIZON, seed.horizon),
        (ESSENTIAL_REQUIREMENTS, seed.requirements),
    )
    return tuple(
        CriterionStatement.stated(name, value, evidence=seed.message)
        for name, value in values
    )


async def _advance_crm(
    session: AsyncSession, actor: Actor, opportunity: Opportunity, seed: CrmSeed
) -> None:
    management = OpportunityManagement(session)
    moment = datetime.now(tz=UTC)
    qualification_stages = {
        OpportunityStage.QUALIFIED,
        OpportunityStage.SEARCHING,
        OpportunityStage.VISITING,
        OpportunityStage.NEGOTIATING,
        OpportunityStage.DORMANT,
        OpportunityStage.WON,
    }
    current = OpportunityStage(opportunity.stage)
    assert opportunity.property_need_id is not None
    await PropertyNeeds(session).record(
        actor, opportunity.property_need_id, _criteria(seed), now=moment
    )
    if (
        seed.target in qualification_stages
        and current is OpportunityStage.IN_CONVERSATION
    ):
        await management.record(
            actor,
            AdvanceStage(
                opportunity_id=opportunity.id,
                to_stage=OpportunityStage.QUALIFIED,
                reason="SyntheticDemoCriteriaConfirmed",
                command_key=(f"sandbox-qualify:{seed.key}:{opportunity.id}:v2"),
                at=moment,
                qualification_action=QualificationAction(
                    kind=NextActionKind.SEND_LISTINGS,
                    due_at=moment + timedelta(days=1),
                    note="Compartir una selección que coincida con los criterios confirmados.",
                ),
            ),
        )
        current = OpportunityStage.QUALIFIED

    for step in (
        OpportunityStage.SEARCHING,
        OpportunityStage.VISITING,
        OpportunityStage.NEGOTIATING,
    ):
        if seed.target in {
            step,
            OpportunityStage.NEGOTIATING,
            OpportunityStage.WON,
        } and current.value in {
            OpportunityStage.QUALIFIED.value,
            OpportunityStage.SEARCHING.value,
            OpportunityStage.VISITING.value,
        }:
            if current is step:
                continue
            await management.record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity.id,
                    to_stage=step,
                    reason="SyntheticDemoProgress",
                    command_key=(
                        f"sandbox-stage:{seed.key}:{opportunity.id}:{step.value}:v2"
                    ),
                    at=moment,
                ),
            )
            current = step
            if current is seed.target:
                break

    if seed.target is OpportunityStage.DORMANT and current is not seed.target:
        await management.record(
            actor,
            RecordDormant(
                opportunity_id=opportunity.id,
                reason=DormantReason.AWAITING_FINANCING,
                revisit_condition="Retomar cuando el banco confirme el crédito.",
                command_key=f"sandbox-dormant:{seed.key}:{opportunity.id}:v2",
                at=moment,
            ),
        )
        current = OpportunityStage.DORMANT
    elif seed.target is OpportunityStage.LOST and current is not seed.target:
        await management.record(
            actor,
            RecordLost(
                opportunity_id=opportunity.id,
                reason=LostReason.BOUGHT_ELSEWHERE,
                detail="El contacto confirmó que compró otra propiedad.",
                command_key=f"sandbox-lost:{seed.key}:{opportunity.id}:v2",
                at=moment,
            ),
        )
        current = OpportunityStage.LOST
    elif seed.target is OpportunityStage.WON and current is not seed.target:
        await management.record(
            actor,
            RecordWon(
                opportunity_id=opportunity.id,
                evidence=WonEvidence.SIGNED_RENTAL_AGREEMENT,
                evidence_detail="Contrato sintético de renta firmado para la demostración local.",
                command_key=f"sandbox-won:{seed.key}:{opportunity.id}:v2",
                at=moment,
            ),
        )
        current = OpportunityStage.WON

    if current in {
        OpportunityStage.IN_CONVERSATION,
        OpportunityStage.QUALIFIED,
        OpportunityStage.SEARCHING,
        OpportunityStage.VISITING,
        OpportunityStage.NEGOTIATING,
    }:
        assigned = await Assignment(session).assign(actor, opportunity.id)
        if assigned.advisor_id is not None and seed.action_kind:
            action_key = f"sandbox-action:{seed.key}:{opportunity.id}:v2"
            existing_action = await session.scalar(
                select(NextAction).where(
                    NextAction.organization_id == actor.organization_id,
                    NextAction.command_key == action_key,
                )
            )
            if existing_action is None:
                await NextActions(session).schedule(
                    actor,
                    ScheduleNextAction(
                        opportunity_id=opportunity.id,
                        kind=seed.action_kind,
                        due_at=moment + timedelta(days=seed.action_due_days),
                        note=f"Acción sintética para {seed.name}.",
                        command_key=action_key,
                        at=moment,
                    ),
                )
        if seed.release_assignment and assigned.advisor_id is not None:
            await Assignment(session).release(actor, opportunity.id)
    await session.commit()


async def _seed_crm(session: AsyncSession, actor: Actor) -> int:
    phone_number_id = await session.scalar(
        select(OrganizationChannelBinding.external_id).where(
            OrganizationChannelBinding.organization_id == actor.organization_id,
            OrganizationChannelBinding.kind
            == ChannelBindingKind.WHATSAPP_PHONE_NUMBER.value,
            OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value,
        )
    )
    if not phone_number_id:
        raise RuntimeError(
            "La organización no tiene un número de WhatsApp vinculado; no se sembró CRM."
        )

    for index, seed in enumerate(CRM_SEEDS):
        inboxes: list[InboxMessage] = []
        conversation: Conversation | None = None
        messages = seed.inbound_messages
        for turn_index, body in enumerate(messages):
            wamid = f"wamid.sandbox.{seed.key}.v2.{turn_index + 1}"
            inbox = await session.scalar(
                select(InboxMessage).where(
                    InboxMessage.organization_id == actor.organization_id,
                    InboxMessage.wamid == wamid,
                )
            )
            if inbox is None:
                accepted = await InboxService(session).accept(
                    InboundMessage(
                        wamid=wamid,
                        from_wa_id=seed.wa_id,
                        phone_number_id=phone_number_id,
                        message_type="text",
                        sent_at=(
                            datetime.now(tz=UTC)
                            - timedelta(hours=index + 1)
                            - timedelta(minutes=(len(messages) - turn_index - 1) * 8)
                        ),
                        text=body,
                        profile_name=seed.name,
                        raw={
                            "id": wamid,
                            "from": seed.wa_id,
                            "type": "text",
                            "text": {"body": body},
                            "synthetic": True,
                        },
                    )
                )
                inbox = await session.get(InboxMessage, accepted.inbox_id)
            if inbox is None:
                raise RuntimeError(f"No se persistió el mensaje de {seed.name}.")
            inbox.status = InboxStatus.PROCESSED.value
            inboxes.append(inbox)
            conversation = await session.get(Conversation, inbox.conversation_id)
            if conversation is None:
                raise RuntimeError(f"No se encontró la conversación de {seed.name}.")

        assert conversation is not None
        opportunity = await CommercialIntake(session).opportunity_for_conversation(
            conversation
        )
        if opportunity is None:
            lead = await session.get(Lead, conversation.lead_id)
            if lead is None:
                raise RuntimeError(f"No se encontró el Lead de {seed.name}.")
            recovered = await CommercialIntake(session).record_inbound(
                lead=lead,
                conversation=conversation,
                inbox_id=inboxes[-1].id,
            )
            opportunity = await session.get(Opportunity, recovered.opportunity_id)
        if opportunity is None:
            opportunity = await session.scalar(
                select(Opportunity)
                .join(
                    OpportunityOrigin,
                    OpportunityOrigin.opportunity_id == Opportunity.id,
                )
                .where(
                    Opportunity.organization_id == actor.organization_id,
                    OpportunityOrigin.first_conversation_id == conversation.id,
                )
            )
        if opportunity is None:
            raise RuntimeError(f"No se creó la oportunidad de {seed.name}.")
        await _advance_crm(session, actor, opportunity, seed)
        if seed.reply is not None:
            queued = await OutboundMessaging(session).request(
                OutboundIntent(
                    conversation=conversation,
                    body=seed.reply,
                    purpose=Purpose.AGENT_REPLY,
                    initiation=OutboundInitiation.REACTIVE,
                    idempotency_key=(
                        f"sandbox-agent-reply:{seed.key}:{conversation.id}:v2"
                    ),
                    trigger_inbox_ids=(inboxes[-1].id,),
                )
            )
            if not isinstance(queued, Queued):
                raise RuntimeError(
                    f"Product rechazó la respuesta sintética para {seed.name}: "
                    f"{queued.reason.value}."
                )
            outbox = await session.get(OutboxMessage, queued.outbox_id)
            if outbox is None:
                raise RuntimeError(
                    f"No se persistió la respuesta sintética para {seed.name}."
                )
            if outbox.status != OutboxStatus.SENT.value:
                # The Sandbox has no external recipient. Record the same
                # provider-success state the worker would, with an unmistakably
                # synthetic provider identifier, so CRM reply status is real.
                outbox.status = OutboxStatus.SENDING.value
                outbox.attempts += 1
                await OutboxService(session).record_result(
                    outbox,
                    SendResult(
                        SendOutcome.SENT,
                        provider_message_id=(f"wamid.sandbox.outbound.{seed.key}.v2"),
                    ),
                )
    return len(CRM_SEEDS)


async def _seed_reactivation(session: AsyncSession, actor: Actor) -> int:
    """Create reviewable matches without authorizing an outbound message."""
    listings = await session.scalars(
        select(CatalogListing)
        .where(
            CatalogListing.organization_id == actor.organization_id,
            CatalogListing.publication_state == ListingPublicationState.PUBLISHED.value,
        )
        .order_by(CatalogListing.created_at)
    )
    for listing in listings:
        await Reactivation(session, actor).discover(listing.id)
    await session.commit()
    return int(
        len(
            list(
                await session.scalars(
                    select(ReactivationCandidate).where(
                        ReactivationCandidate.organization_id == actor.organization_id
                    )
                )
            )
        )
    )


async def _seed_sponsorship(session: AsyncSession, actor: Actor) -> int:
    """Build one sellable placement through pricing, quoting and activation."""
    moment = datetime.now(tz=UTC)
    pricing = SponsorshipPricing(session, actor)
    catalog = await pricing.draft(
        DraftCatalog(
            version=SPONSORSHIP_CATALOG_VERSION,
            currency="MXN",
            lines=(
                PriceLine("Search", 30, Decimal("4000")),
                PriceLine("Homepage", 30, Decimal("7000")),
                PriceLine("Both", 30, Decimal("9500")),
            ),
            command_key=f"catalog:{SPONSORSHIP_CATALOG_VERSION}",
        ),
        at=moment,
    )
    if catalog.status == PriceCatalogStatus.DRAFT.value:
        await pricing.publish(
            PublishCatalog(
                catalog.catalog_id,
                "Datos sintéticos del piloto local; importes exclusivos del sandbox.",
            ),
            at=moment,
        )

    existing = await session.scalar(
        select(SponsorshipCampaign).where(
            SponsorshipCampaign.organization_id == actor.organization_id,
            SponsorshipCampaign.buyer_label == SPONSORSHIP_BUYER_LABEL,
        )
    )
    if existing is None:
        listing = await session.scalar(
            select(CatalogListing).where(
                CatalogListing.organization_id == actor.organization_id,
                CatalogListing.listing_key == "casa-nispero-legacy",
            )
        )
        if listing is None:
            raise RuntimeError("No se encontró Casa Níspero para patrocinio.")
        campaigns = SponsorshipCampaigns(session, actor)
        opened = await campaigns.open(
            OpenCampaign(
                listing_id=listing.id,
                buyer_kind="Owner",
                buyer_label=SPONSORSHIP_BUYER_LABEL,
                package="Both",
                paid_days=30,
                command_key="sandbox-sponsorship:casa-nispero:v1",
            ),
            at=moment,
        )
        await campaigns.record_clearance(
            opened.campaign_id,
            "Validación comercial sintética: ficha, precio, autoridad y medios revisados.",
            at=moment,
        )
        quote = await SponsorshipQuoting(session, actor).quote(
            QuoteCommand(
                campaign_id=opened.campaign_id,
                command_key="sandbox-sponsorship-quote:casa-nispero:v1",
                duration_days=30,
            ),
            at=moment,
        )
        await SponsorshipQuoting(session, actor).accept(
            AcceptQuote(quote.quote_id, moment), at=moment
        )
        await campaigns.schedule(
            ScheduleCampaign(opened.campaign_id, moment), at=moment
        )
        await campaigns.activate(opened.campaign_id, at=moment)
        await campaigns.record_collection(
            RecordCollection(
                opened.campaign_id,
                CollectionState.COLLECTED,
                "SANDBOX-NO-PAYMENT",
            ),
            at=moment,
        )
        existing = await session.get(SponsorshipCampaign, opened.campaign_id)

    assert existing is not None
    live_link = await session.scalar(
        select(SponsorshipReportLink).where(
            SponsorshipReportLink.organization_id == actor.organization_id,
            SponsorshipReportLink.campaign_id == existing.id,
            SponsorshipReportLink.revoked_at.is_(None),
            SponsorshipReportLink.expires_at > moment,
        )
    )
    if live_link is None:
        await SponsorshipSharing(session, actor).share(existing.id, at=moment, days=14)
    await session.commit()
    return int(
        len(
            list(
                await session.scalars(
                    select(SponsorshipCampaign).where(
                        SponsorshipCampaign.organization_id == actor.organization_id
                    )
                )
            )
        )
    )


async def _seed_calendar(
    session: AsyncSession, actor: Actor, settings: Settings
) -> int:
    """Book one real Google event, only when the CLI explicitly requests it."""
    inbox = await session.scalar(
        select(InboxMessage).where(
            InboxMessage.organization_id == actor.organization_id,
            InboxMessage.wamid == "wamid.sandbox.visiting.v1",
        )
    )
    listing = await session.scalar(
        select(CatalogListing).where(
            CatalogListing.organization_id == actor.organization_id,
            CatalogListing.listing_key == "casa-patio-legacy",
        )
    )
    if inbox is None or listing is None or listing.property_uuid is None:
        raise RuntimeError("Falta el caso sintético requerido para agendar.")
    existing = await session.scalar(
        select(Appointment).where(
            Appointment.organization_id == actor.organization_id,
            Appointment.conversation_id == inbox.conversation_id,
            Appointment.property_uuid == listing.property_uuid,
            Appointment.status.in_(
                {
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                    AppointmentStatus.NEEDS_REVIEW.value,
                }
            ),
        )
    )
    if existing is not None:
        return 1

    opportunity = await session.scalar(
        select(Opportunity)
        .join(
            OpportunityOrigin,
            OpportunityOrigin.opportunity_id == Opportunity.id,
        )
        .where(
            Opportunity.organization_id == actor.organization_id,
            OpportunityOrigin.first_conversation_id == inbox.conversation_id,
        )
    )
    if opportunity is None:
        raise RuntimeError("No existe la oportunidad sintética para la visita.")
    assignment = await session.scalar(
        select(OpportunityAssignment).where(
            OpportunityAssignment.opportunity_id == opportunity.id,
            OpportunityAssignment.unassigned_at.is_(None),
        )
    )
    if assignment is None:
        raise RuntimeError("La visita sintética no tiene asesor responsable.")

    policy = AppointmentPolicy(
        schedule=WeeklySchedule.parse(settings.weekly_schedule, settings.timezone),
        visit_minutes=settings.visit_minutes,
        horizon_days=settings.booking_horizon_days,
        max_candidates=settings.max_slot_candidates,
        day_of_reminder_hour=settings.appointment_day_of_reminder_hour,
    )
    scheduling = AdvisorScheduling(
        session,
        GoogleCalendarDirectory(settings.google_calendar_credentials),
        policy.scheduling,
    )
    available = await scheduling.find_slots(
        SlotQuery(
            organization_id=actor.organization_id,
            advisor_id=assignment.advisor_id,
            limit=settings.max_slot_candidates,
        )
    )
    if isinstance(available, SlotsUnavailable):
        raise RuntimeError(
            f"Google Calendar rechazó la consulta: {available.reason.value}: "
            f"{available.detail or available.message}"
        )
    if not available.slots:
        raise RuntimeError(
            "Google Calendar no devolvió horarios libres en el horizonte."
        )
    outcome = await Appointments(
        session,
        scheduling,
        schedule=policy.schedule,
        day_of_reminder_hour=policy.day_of_reminder_hour,
        max_candidates=policy.max_candidates,
        event_title=policy.event_title,
    ).book(
        actor,
        BookVisit(
            conversation_id=inbox.conversation_id,
            property_uuid=listing.property_uuid,
            start=available.slots[0].start,
            command_key="sandbox-book-visit:casa-patio:v1",
            attendee_name="Demo · Diego Ortiz",
        ),
    )
    if isinstance(outcome, VisitRefused):
        raise RuntimeError(
            f"La reserva fue rechazada: {outcome.reason.value}: "
            f"{outcome.detail or outcome.message}"
        )
    if not outcome.confirmed:
        raise RuntimeError(
            "Google Calendar dio un resultado inconcluso; la cita quedó para revisión."
        )
    return 1


async def _synchronize_meta_templates(
    session: AsyncSession, actor: Actor, settings: Settings
) -> int:
    """Refresh provider-owned template truth; never creates a local approval."""
    sources = OrganizationMetaTemplateSources(
        SecretResolver(),
        bootstrap_organization_id=actor.organization_id,
        legacy_access_token=settings.meta_access_token,
        graph_version=settings.meta_graph_version,
        base_url=settings.meta_graph_base_url,
    )
    try:
        source = await sources.for_organization(session, actor.organization_id)
        result = await TemplateRegistry(session).synchronize(actor, source)
        await session.commit()
        return result.observed
    finally:
        await sources.aclose()


async def _seed_development_campaign(session: AsyncSession, actor: Actor) -> int:
    """Plan a bounded audience from real Meta template observations."""
    existing_campaign = await session.scalar(
        select(DevelopmentCampaign).where(
            DevelopmentCampaign.organization_id == actor.organization_id,
            DevelopmentCampaign.name == DEVELOPMENT_CAMPAIGN_NAME,
        )
    )
    if existing_campaign is not None:
        return 1

    template = await session.scalar(
        select(ApprovedMessageTemplate)
        .where(
            ApprovedMessageTemplate.organization_id == actor.organization_id,
            ApprovedMessageTemplate.category == ConsentCategory.MARKETING.value,
            ApprovedMessageTemplate.provider_status
            == MessageTemplateStatus.APPROVED.value,
            ApprovedMessageTemplate.retired_at.is_(None),
        )
        .order_by(ApprovedMessageTemplate.template_name)
    )
    if template is None or not template.body_text.strip():
        return 0

    catalog = CatalogAdministration(session)
    development = await session.scalar(
        select(Development).where(
            Development.organization_id == actor.organization_id,
            Development.development_key == DEVELOPMENT_KEY,
        )
    )
    facts = {
        "service_area": "Zapopan",
        "authority": "SyntheticLocalSandbox",
        "marketing_authority_confirmed": True,
    }
    if development is None:
        created = await catalog.record(
            actor,
            CreateDevelopment(
                development_key=DEVELOPMENT_KEY,
                name="Parque Norte",
                facts=facts,
                provenance={
                    "kind": "SyntheticLocalSandbox",
                    "note": "Desarrollo ficticio para verificar el pipeline local.",
                },
                command_key="sandbox-development:parque-norte:v2",
            ),
        )
        development = await session.get(Development, created.subject_id)
    if development is None:
        raise RuntimeError("No se pudo crear el desarrollo sintético.")
    if development.facts_review_state != FactsReviewState.APPROVED.value:
        await catalog.record(
            actor,
            ReviewDevelopmentFacts(
                development_id=development.id,
                review_state=FactsReviewState.APPROVED,
                facts=facts,
                command_key=(
                    f"sandbox-development-review:parque-norte:{development.id}:v2"
                ),
            ),
        )

    need_ids = tuple(
        dict.fromkeys(
            value
            for value in await session.scalars(
                select(Opportunity.property_need_id).where(
                    Opportunity.organization_id == actor.organization_id,
                    Opportunity.property_need_id.is_not(None),
                    Opportunity.stage.not_in(
                        {OpportunityStage.WON.value, OpportunityStage.LOST.value}
                    ),
                )
            )
            if value is not None
        )
    )
    if not need_ids:
        raise RuntimeError("No existen necesidades para resolver la audiencia.")
    await Campaigns(session, actor, activation_approved=False).plan(
        PlanCampaign(
            development_id=development.id,
            name=DEVELOPMENT_CAMPAIGN_NAME,
            property_need_ids=need_ids,
            template_name=template.template_name,
            template_language=template.language_code,
            content_preview=template.body_text,
            service_area_contains="Zapopan",
            frequency_cap=1,
            frequency_window_days=30,
            max_recipients=50,
        )
    )
    await session.commit()
    return 1


async def seed(
    settings: Settings,
    *,
    confirmed: bool,
    book_calendar: bool = False,
    sync_meta_templates: bool = False,
) -> dict[str, int]:
    require_local_sandbox(settings, confirmed=confirmed)
    database = Database(settings.database_url)
    storage = media_storage_from_settings(settings)
    try:
        async with database.session_scope() as session:
            organization = await session.scalar(
                select(Organization).where(
                    Organization.slug == settings.platform_bootstrap_organization_slug
                )
            )
            if organization is None:
                raise RuntimeError("No existe la organización bootstrap configurada.")
            admin_member = await session.scalar(
                select(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == organization.id,
                    OrganizationMember.active.is_(True),
                    OrganizationMember.role == "OrganizationAdministrator",
                )
                .order_by(OrganizationMember.created_at)
            )
            if admin_member is None:
                raise RuntimeError(
                    "No hay un administrador activo para ejecutar la carga."
                )
            actor = await OrganizationDirectory(session).resolve_actor(
                admin_member.login
            )
            created, published = await _seed_inventory(
                session, actor, settings, storage
            )
            crm = await _seed_crm(session, actor)
            templates = (
                await _synchronize_meta_templates(session, actor, settings)
                if sync_meta_templates
                else 0
            )
            reactivation = await _seed_reactivation(session, actor)
            development_campaigns = await _seed_development_campaign(session, actor)
            sponsorship = await _seed_sponsorship(session, actor)
            appointments = (
                await _seed_calendar(session, actor, settings) if book_calendar else 0
            )
            return {
                "properties_created": created,
                "properties_total": len(PROPERTY_SEEDS),
                "listings_published": published,
                "crm_contacts_total": crm,
                "reactivation_candidates_total": reactivation,
                "sponsorship_campaigns_total": sponsorship,
                "development_campaigns_total": development_campaigns,
                "appointments_total": appointments,
                "meta_templates_observed": templates,
            }
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-local-sandbox", action="store_true")
    parser.add_argument(
        "--book-calendar",
        action="store_true",
        help="Reserva una cita sintética real en Google Calendar.",
    )
    parser.add_argument(
        "--sync-meta-templates",
        action="store_true",
        help="Actualiza la verdad de plantillas desde Meta sin aprobar nada localmente.",
    )
    arguments = parser.parse_args()
    result = asyncio.run(
        seed(
            get_settings(),
            confirmed=arguments.confirm_local_sandbox,
            book_calendar=arguments.book_calendar,
            sync_meta_templates=arguments.sync_meta_templates,
        )
    )
    print(
        "Carga local confirmada: "
        f"{result['properties_total']} propiedades, "
        f"{result['crm_contacts_total']} contactos CRM, "
        f"{result['reactivation_candidates_total']} candidatos de reactivación, "
        f"{result['development_campaigns_total']} campaña de desarrollo, "
        f"{result['sponsorship_campaigns_total']} campaña patrocinada y "
        f"{result['appointments_total']} cita de Calendar; "
        f"{result['meta_templates_observed']} plantillas observadas en Meta."
    )


if __name__ == "__main__":
    main()
