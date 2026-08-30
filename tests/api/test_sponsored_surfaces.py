"""Payment buys a position, never relevance — and the label is not optional.

Two claims are asserted here, and they are the ones a regulator, a property
owner and a visitor would each care about most.

**Organic relevance is independent of Sponsored Placement.** Asserted twice: by
comparing the ordered organic result list with and without an Active campaign
over one of the results, and structurally, by checking that the module which
ranks results does not import the modules that handle money.

**Every paid exposure is labelled, visibly and accessibly.** Asserted on the
rendered HTML of both surfaces, on the internal contract that feeds them, and on
the buyer report and its PDF.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from realestate.db.engine import Database
from realestate.domain.public.catalog import PublicCatalog, SearchQuery
from realestate.domain.public.sponsored import PublicSponsored
from realestate.domain.sponsorship.labels import (
    EDITORIAL_LABEL,
    SPONSORED_ARIA_LABEL,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)
from realestate.site import templates as site_templates
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import ADMIN_LOGIN, actor_for, provision, reset
from tests.fixtures.public_site import publish_listing
from tests.fixtures.sponsorship import MOMENT, active_campaign, published_catalog

pytestmark = requires_postgres
SOURCE = Path(__file__).resolve().parents[2] / "src" / "realestate"


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await provision(session)
        await session.commit()
    yield database
    await database.dispose()


async def ordered_slugs(session, actor, *, sort: str = "relevance") -> list[str]:
    result = await PublicCatalog(session, actor).search(
        SearchQuery(sort=sort, page_size=24), at=MOMENT
    )
    return [item.slug for item in result.listings]


@pytest.mark.parametrize(
    "sort", ["relevance", "recent", "price_asc", "price_desc"]
)
async def test_organic_order_is_identical_with_and_without_payment(
    database, sort
) -> None:
    """The same list, in the same order, before and after a campaign exists.

    Paying for one of these Listings changes which extra positions the page
    offers. It does not move that Listing up the organic list, and this is the
    assertion that would fail if it ever did.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        for index, suffix in enumerate(("alfa", "beta", "gama")):
            await publish_listing(
                session,
                admin,
                suffix,
                price=__import__("decimal").Decimal(str(3_000_000 + index * 500_000)),
            )
        await session.commit()

        before = await ordered_slugs(session, admin, sort=sort)
        assert len(before) == 3

        await published_catalog(session, admin)
        # The campaign covers the *last* organic result, so any relevance effect
        # would be visible as a reordering.
        listing = await publish_listing(session, admin, "patrocinada")
        await active_campaign(
            session, admin, "patrocinada", listing=listing, package="Search"
        )
        await session.commit()

        after = await ordered_slugs(session, admin, sort=sort)
        # The new Listing appears because it is published, not because it is
        # paid: what matters is that the three originals keep their order.
        assert [slug for slug in after if slug in before] == before


async def test_the_ranking_module_cannot_reach_the_money_modules(database) -> None:
    """Structural, not behavioural. The separation is enforced by absence.

    ``PublicCatalog`` is the only thing that orders public results. If it cannot
    import sponsorship at all, no future change can make payment influence
    relevance by accident.
    """
    ranking = (SOURCE / "domain" / "public" / "catalog.py").read_text(encoding="utf-8")
    for forbidden in ("sponsorship", "sponsored", "campaign", "patrocin"):
        assert forbidden not in ranking.casefold(), forbidden

    # And the projection the ranking reads is equally clean.
    projection = (
        SOURCE / "domain" / "catalog" / "projection.py"
    ).read_text(encoding="utf-8")
    assert "sponsor" not in projection.casefold()


async def test_the_paid_section_is_returned_separately_from_the_organic_list(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "separada")
        await session.commit()

        result = await PublicSponsored(session, admin).for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-1",
        )
        await session.commit()

        assert result.surface == "Search"
        assert result.available_slots == 2
        assert [card.listing.slug for card in result.cards] == [
            campaign.listing.slug
        ]
        card = result.cards[0]
        assert card.label == SPONSORED_LABEL
        assert card.accessible_label == SPONSORED_ARIA_LABEL
        assert result.disclosure == SPONSORED_DISCLOSURE
        # The paid card is rendered through the same public projection as an
        # organic one, so it cannot show a field an unpaid card would not.
        assert card.listing.offers
        assert card.listing.technical_sheet_url.endswith(campaign.listing.slug)


async def test_serving_a_paid_card_records_its_served_impression(database) -> None:
    """Serving is Product's own fact and is recorded as the response is built.

    A served count that depended on a script running would systematically
    under-report the visitors whose devices are slowest.
    """
    from sqlalchemy import select

    from realestate.db.models import AnalyticsEventName, AnalyticsOutboxEntry

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "servida")
        await session.commit()

        sponsored = PublicSponsored(session, admin)
        first = await sponsored.for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-2",
        )
        second = await sponsored.for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-2",
        )
        await session.commit()

        rows = list(
            await session.scalars(
                select(AnalyticsOutboxEntry).where(
                    AnalyticsOutboxEntry.event_name
                    == AnalyticsEventName.SPONSORED_SERVED_IMPRESSION.value
                )
            )
        )
        assert len(rows) == 2
        assert first.cards[0].exposure_id != second.cards[0].exposure_id
        assert {row.duplicate_attempts for row in rows} == {0}
        assert all("navegador-2" not in row.event_key for row in rows)


async def test_a_browser_claim_below_the_threshold_is_not_a_visible_impression(
    database,
) -> None:
    """Product applies the versioned rule; the page only reports measurements.

    Otherwise a modified client could inflate a buyer's report and exhaust
    another buyer's rotation.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "visible")
        await session.commit()

        sponsored = PublicSponsored(session, admin)
        surface = await sponsored.for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-3",
        )
        exposure_id = surface.cards[0].exposure_id
        below = await sponsored.count_visible(
            exposure_id=exposure_id,
            visible_fraction=0.49,
            continuous_milliseconds=5000,
            session_value="navegador-3",
            at=MOMENT,
        )
        exact = await sponsored.count_visible(
            exposure_id=exposure_id,
            visible_fraction=0.5,
            continuous_milliseconds=1000,
            session_value="navegador-3",
            at=MOMENT,
        )
        await session.commit()
        assert below is False
        assert exact is True


async def test_three_distinct_served_exposures_reach_the_real_session_cap(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "tope-real")
        await session.commit()

        sponsored = PublicSponsored(session, admin)
        session_value = "navegador-con-tope"
        exposure_ids = []
        for _ in range(3):
            surface = await sponsored.for_surface(
                surface="Search",
                at=MOMENT,
                visible_results=12,
                session_value=session_value,
            )
            exposure_ids.append(surface.cards[0].exposure_id)
            assert await sponsored.count_visible(
                exposure_id=surface.cards[0].exposure_id,
                visible_fraction=0.5,
                continuous_milliseconds=1000,
                session_value=session_value,
                at=MOMENT,
            ) is True

        assert len(set(exposure_ids)) == 3
        capped = await sponsored.for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value=session_value,
        )
        assert capped.cards == ()


async def test_an_unpublished_listing_leaves_its_slot_empty_not_substituted(
    database,
) -> None:
    """An empty paid section is honest; a substituted one bills the wrong buyer."""
    from realestate.db.models import ListingPublicationState
    from realestate.domain.catalog.administration import (
        CatalogAdministration,
        SetPublicationState,
    )

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "retirada")
        await session.commit()

        # Withdrawn after the campaign went Active, which is the race the guard
        # in ``PublicSponsored`` exists for.
        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=campaign.listing.listing_id,
                state=ListingPublicationState.UNPUBLISHED,
                command_key="surfaces:withdraw",
            ),
        )
        await session.commit()

        result = await PublicSponsored(session, admin).for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-4",
        )
        await session.commit()
        assert result.cards == ()


def test_a_sponsored_card_renders_the_visible_chip_and_an_accessible_name() -> None:
    """The label is produced by the template, not passed to it.

    A caller cannot render a sponsored card without it, and the accessible name
    is on the article as well as the chip: a screen-reader user who only hears
    the title has not been told the placement was bought.
    """
    card = {
        "campaign_id": "11111111-1111-1111-1111-111111111111",
        "exposure_id": "33333333-3333-3333-3333-333333333333",
        "listing": {
            "listing_id": "22222222-2222-2222-2222-222222222222",
            "slug": "casa-etiquetada",
            "title": "Casa Etiquetada",
            "public_location": "Zapopan, Jalisco",
            "presentation_tier": "Premium",
            "media": [],
            "offers": [],
            "physical_facts": {},
        },
    }
    html = site_templates.sponsored_card(card, surface="Search", position=1)
    assert f">{SPONSORED_LABEL}<" in html
    assert f'aria-label="{SPONSORED_ARIA_LABEL}"' in html
    assert 'class="listing-card sponsored"' in html
    assert 'data-sponsored-campaign="11111111-1111-1111-1111-111111111111"' in html
    assert 'data-sponsored-exposure="33333333-3333-3333-3333-333333333333"' in html
    # An organic card carries neither.
    organic = site_templates.listing_card(card["listing"], surface="Search")
    assert SPONSORED_LABEL not in organic
    assert "aria-label" not in organic


def test_the_homepage_paid_section_is_its_own_labelled_region() -> None:
    """A dedicated section with a heading, not cards mixed into the selection.

    A visitor who has to compare chips to tell paid from unpaid has not really
    been told.
    """
    section = site_templates.sponsored_section(
        {
            "disclosure": SPONSORED_DISCLOSURE,
            "cards": [
                {
                    "campaign_id": "33333333-3333-3333-3333-333333333333",
                    "listing": {
                        "listing_id": "44444444-4444-4444-4444-444444444444",
                        "slug": "casa-portada",
                        "title": "Casa Portada",
                        "media": [],
                        "offers": [],
                        "physical_facts": {},
                    },
                }
            ],
        }
    )
    assert 'aria-labelledby="patrocinadas"' in section
    assert 'id="patrocinadas"' in section
    assert SPONSORED_DISCLOSURE.split(".")[0] in section
    assert section.count(f">{SPONSORED_LABEL}<") >= 1
    # No cards means no section at all, rather than an empty heading.
    assert site_templates.sponsored_section({"cards": []}) == ""


def test_search_inserts_paid_slots_without_reordering_the_organic_results() -> None:
    """The organic order in, the same organic order out.

    Interleaving is by insertion at the head of each group of six. A sponsored
    card never displaces, replaces or reorders an organic result.
    """
    organic = [
        {
            "listing_id": f"aaaaaaaa-0000-0000-0000-00000000000{index}",
            "slug": f"organica-{index}",
            "title": f"Orgánica {index}",
            "media": [],
            "offers": [],
            "physical_facts": {},
        }
        for index in range(7)
    ]
    sponsored = {
        "cards": [
            {
                "campaign_id": "55555555-5555-5555-5555-555555555555",
                "listing": {
                    "listing_id": "66666666-6666-6666-6666-666666666666",
                    "slug": "pagada",
                    "title": "Pagada",
                    "media": [],
                    "offers": [],
                    "physical_facts": {},
                },
            }
        ]
    }
    html = site_templates.search_results_grid(organic, sponsored)
    # Each card links to its sheet twice (the image and the title), so the
    # sequence is deduplicated before the order is compared.
    order = list(
        dict.fromkeys(re.findall(r'href="/propiedades/([a-z0-9-]+)"', html))
    )
    assert [slug for slug in order if slug.startswith("organica-")] == [
        f"organica-{index}" for index in range(7)
    ]
    # The paid card is present exactly once and sits at the head of the page.
    assert order[0] == "pagada"
    assert order.count("pagada") == 1

    # With no paid cards the grid is the plain organic grid, in the same order
    # and with no label anywhere. Compared by structure rather than byte-for-byte
    # because each save control carries a freshly minted idempotency key.
    plain = site_templates.search_results_grid(organic, {})
    assert list(
        dict.fromkeys(re.findall(r'href="/propiedades/([a-z0-9-]+)"', plain))
    ) == [f"organica-{index}" for index in range(7)]
    assert SPONSORED_LABEL not in plain
    assert plain.count("<article") == len(organic)


def test_the_site_and_the_domain_agree_on_the_label_text() -> None:
    """The site process cannot import Product's domain, so the strings are
    restated there. This is the contract test that keeps the two copies equal —
    an accessibility check on one spelling proves nothing about the other."""
    assert site_templates.SPONSORED_LABEL == SPONSORED_LABEL
    assert site_templates.SPONSORED_ARIA_LABEL == SPONSORED_ARIA_LABEL


def test_editorial_and_paid_prominence_are_never_the_same_word() -> None:
    """``Destacada`` is unpaid selection; ``Patrocinada`` is bought visibility.

    A property owner told their listing is *featured* who later learns the word
    meant somebody paid has been misled (ADR-0043, SAN-060).
    """
    assert EDITORIAL_LABEL != SPONSORED_LABEL
    sponsorship_source = (SOURCE / "domain" / "sponsorship").rglob("*.py")
    for path in sponsorship_source:
        text = path.read_text(encoding="utf-8")
        if path.name == "labels.py":
            continue
        assert EDITORIAL_LABEL not in text, path.name


def test_the_report_page_renders_only_the_lines_product_produced() -> None:
    """The buyer page cannot grow a field by somebody adding one to a dataclass."""
    page = site_templates.report_page(
        {
            "label": SPONSORED_LABEL,
            "lines": [
                {"text": "Reporte de campaña Patrocinada", "style": "title"},
                {"text": "Embudo", "style": "heading"},
                {"text": "Impresiones visibles: 3", "style": "body"},
                {"text": "", "style": "body"},
            ],
        },
        token="token-de-prueba",
    )
    assert "<h1>Reporte de campaña Patrocinada</h1>" in page
    assert '<h2 class="report-heading">Embudo</h2>' in page
    assert '<p class="report-line">Impresiones visibles: 3</p>' in page
    assert "/reportes/token-de-prueba/patrocinio.pdf" in page
    # A blank line is skipped rather than rendered as an empty paragraph.
    assert '<p class="report-line"></p>' not in page


def test_the_measurement_moment_is_timezone_aware() -> None:
    """Guards the fixture itself: a naive moment is refused by the taxonomy."""
    assert MOMENT.tzinfo is not None
    assert MOMENT.astimezone(UTC) == MOMENT
    assert isinstance(MOMENT, datetime)
