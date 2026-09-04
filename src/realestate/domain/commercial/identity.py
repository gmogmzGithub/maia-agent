"""Which person is this? — the one place a channel identity becomes a Contact.

A Contact is a person across time. A channel identity is an address the
platform authenticated. Keeping them separate is what lets a Contact outlive
every conversation they ever had, hold several Property Needs at once, and be
reachable on several channels without their commercial history forking.

The rule for joining them is deliberately narrow: **the same trusted identifier
resolves to the same Contact, and nothing else does.** Similar identifiers stay
separate people. In Mexico that matters concretely — WhatsApp ids for the same
country appear both with and without the historical ``1`` after ``52`` — and a
normalisation that folded them together would be a *claim* that two people are
one, made by a regular expression, on evidence nobody checked. When Product
notices such a pair it says so to a human and takes no action.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.messaging import CustomerChannel
from realestate.db.models import (
    Contact,
    ContactChannelIdentity,
    ChannelIdentityTrust,
    Opportunity,
)
from realestate.domain.audit import record_audit
from realestate.domain.text import fold_mexican_mobile
from realestate.domain.commercial.actors import Actor, NotFound

logger = logging.getLogger(__name__)

class UntrustedIdentity(Exception):
    """The identity cannot be used to resolve a Contact.

    Raised rather than resolved to *some* Contact, because failing closed here
    means one unusable request; guessing means two people's histories merged.
    """


@dataclass(frozen=True)
class ChannelIdentity:
    """One addressable identity presented to Product.

    ``identity`` is the platform's own identifier, kept verbatim. Nothing here
    rewrites it into a canonical phone number: the stored string is what the
    channel said, so a later comparison is against evidence rather than against
    Product's interpretation of it.
    """

    channel: str
    identity: str
    trust: ChannelIdentityTrust
    channel_account_id: str = ""
    #: The durable Lead/channel-address row this corresponds to. Required for
    #: verified customer-message channels so consent and suppression evidence
    #: has an Organization-scoped subject.
    lead_id: uuid.UUID | None = None
    #: A display hint supplied by the channel, when the provider includes one.
    display_name: str | None = None

    @classmethod
    def whatsapp(
        cls,
        *,
        wa_id: str,
        lead_id: uuid.UUID,
        phone_number_id: str = "",
        profile_name: str | None = None,
    ) -> ChannelIdentity:
        """A WhatsApp identity Meta authenticated through a signed webhook."""
        return cls(
            channel=CustomerChannel.WHATSAPP.value,
            channel_account_id=phone_number_id,
            identity=wa_id,
            trust=ChannelIdentityTrust.VERIFIED,
            lead_id=lead_id,
            display_name=profile_name,
        )

    @classmethod
    def customer_message(
        cls,
        *,
        channel: CustomerChannel,
        channel_account_id: str,
        provider_user_id: str,
        lead_id: uuid.UUID,
        profile_name: str | None = None,
    ) -> ChannelIdentity:
        """An identity authenticated by a signed customer-message webhook."""
        return cls(
            channel=channel.value,
            channel_account_id=channel_account_id,
            identity=provider_user_id,
            trust=ChannelIdentityTrust.VERIFIED,
            lead_id=lead_id,
            display_name=profile_name,
        )


@dataclass(frozen=True)
class ResolvedContact:
    """The Contact behind one channel identity."""

    contact_id: uuid.UUID
    identity_id: uuid.UUID
    organization_id: uuid.UUID
    #: Whether this call created the Contact. Callers use it to decide whether
    #: an Opportunity has to be opened, not to decide who the person is.
    created: bool


def national_digits(identity: str) -> str:
    """The look-alike key for one identity.

    Used **only** to flag a possible duplicate to a human. It is deliberately
    not used for lookup: this is the exact transformation that would merge two
    Contacts on a plausible guess.

    It is the same fold the send path applies
    (:func:`~realestate.domain.text.fold_mexican_mobile`), and that is the point.
    Two identifiers that Meta would deliver to the same phone are exactly the
    pair an operator should be asked about.
    """
    return fold_mexican_mobile(identity)


class CommercialIdentity:
    """The seam between channel identity and commercial identity.

    Hides: the trust rule, Organization scoping, the create-or-find race, the
    display-name hint, and the audit event for a new Contact.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self, channel_identity: ChannelIdentity, *, organization_id: uuid.UUID
    ) -> ResolvedContact:
        """Find or create the Contact for one channel identity. Never commits.

        Left uncommitted on purpose: the webhook path resolves the Contact in
        the same transaction that persists the message, so a Contact cannot
        exist because of a message that was never durably stored.
        """
        self._require_usable(channel_identity)

        found = await self._existing(channel_identity, organization_id)
        if found is not None:
            await self._refresh_display_name(found, channel_identity)
            return ResolvedContact(
                contact_id=found.contact_id,
                identity_id=found.id,
                organization_id=found.organization_id,
                created=False,
            )

        # Inside a savepoint, so losing the create race does not poison the
        # caller's transaction — which is also the one persisting the inbound
        # message that triggered this.
        try:
            async with self._session.begin_nested():
                contact = Contact(
                    organization_id=organization_id,
                    display_name=channel_identity.display_name,
                )
                self._session.add(contact)
                await self._session.flush()
                identity = ContactChannelIdentity(
                    organization_id=organization_id,
                    contact_id=contact.id,
                    channel=channel_identity.channel,
                    channel_account_id=channel_identity.channel_account_id,
                    identity=channel_identity.identity,
                    trust=channel_identity.trust.value,
                    lead_id=channel_identity.lead_id,
                )
                self._session.add(identity)
                await self._session.flush()
                contact_id, identity_id = contact.id, identity.id
        except IntegrityError:
            # Two concurrent first messages from the same person raced. The
            # unique index is the arbiter; whoever lost reads the winner.
            winner = await self._existing(channel_identity, organization_id)
            if winner is None:  # pragma: no cover - the index is the only writer
                raise
            logger.info(
                "Lost the Contact creation race for a %s identity; using %s",
                channel_identity.channel,
                winner.contact_id,
            )
            await self._refresh_display_name(winner, channel_identity)
            return ResolvedContact(
                contact_id=winner.contact_id,
                identity_id=winner.id,
                organization_id=winner.organization_id,
                created=False,
            )

        await record_audit(
            self._session,
            organization_id=organization_id,
            actor_type="Product",
            actor_id="CommercialIdentity",
            action="CreateContact",
            subject_type="Contact",
            subject_id=str(contact_id),
            details={
                "channel": channel_identity.channel,
                "trust": channel_identity.trust.value,
                # The identity itself is not copied into the audit detail: the
                # row already holds it, and the audit trail outlives the
                # retention rules that govern personal data.
                "organization_id": str(organization_id),
            },
            commit=False,
        )
        logger.info(
            "Created Contact %s for a new %s identity",
            contact_id,
            channel_identity.channel,
        )
        return ResolvedContact(
            contact_id=contact_id,
            identity_id=identity_id,
            organization_id=organization_id,
            created=True,
        )

    async def contact(self, actor: Actor, contact_id: uuid.UUID) -> Contact:
        """One Contact inside the Actor's Organization, or :class:`NotFound`."""
        contact = await self._session.get(Contact, contact_id)
        if contact is None:
            raise NotFound()
        actor.require_same_organization(contact.organization_id)
        if not actor.sees_whole_operation:
            visible = await self._session.scalar(
                select(Opportunity.id)
                .where(Opportunity.contact_id == contact_id)
                .where(Opportunity.organization_id == actor.organization_id)
                .where(Opportunity.responsible_advisor_id == actor.member_id)
                .limit(1)
            )
            if visible is None:
                raise NotFound("No encontramos ese contacto.")
        return contact

    async def identities(
        self, contact_id: uuid.UUID
    ) -> list[ContactChannelIdentity]:
        rows = await self._session.scalars(
            select(ContactChannelIdentity)
            .where(ContactChannelIdentity.contact_id == contact_id)
            .order_by(ContactChannelIdentity.first_seen_at)
        )
        return list(rows)

    async def contact_for_lead(self, lead_id: uuid.UUID) -> uuid.UUID | None:
        """The Contact behind one durable customer channel identity, if resolved."""
        found: uuid.UUID | None = await self._session.scalar(
            select(ContactChannelIdentity.contact_id).where(
                ContactChannelIdentity.lead_id == lead_id
            )
        )
        return found

    async def possible_duplicates(
        self, actor: Actor, contact_id: uuid.UUID
    ) -> list[ContactChannelIdentity]:
        """Other identities that *look* like this Contact's, for a human to judge.

        Returns candidates, performs no merge, and changes nothing. The whole
        value is that the operator sees the ambiguity instead of Product
        resolving it silently in one direction or the other.
        """
        mine = await self.identities(contact_id)
        whatsapp_mine = [
            row for row in mine if row.channel == CustomerChannel.WHATSAPP.value
        ]
        if not whatsapp_mine:
            return []
        keys = {national_digits(row.identity) for row in whatsapp_mine}
        rows = await self._session.scalars(
            select(ContactChannelIdentity)
            .where(ContactChannelIdentity.organization_id == actor.organization_id)
            .where(ContactChannelIdentity.contact_id != contact_id)
            .where(ContactChannelIdentity.channel == CustomerChannel.WHATSAPP.value)
        )
        return [row for row in rows if national_digits(row.identity) in keys]

    # -- internals ---------------------------------------------------------

    def _require_usable(self, channel_identity: ChannelIdentity) -> None:
        if not channel_identity.identity.strip():
            raise UntrustedIdentity("An empty channel identity resolves to nobody.")
        if channel_identity.channel not in {channel.value for channel in CustomerChannel}:
            raise UntrustedIdentity(
                f"Channel {channel_identity.channel!r} is not a customer channel."
            )
        if channel_identity.lead_id is None:
            raise UntrustedIdentity(
                "A customer identity must name the channel-identity record that "
                "holds its consent and suppression evidence."
            )
        if not channel_identity.channel_account_id.strip() and (
            channel_identity.channel != CustomerChannel.WHATSAPP.value
        ):
            raise UntrustedIdentity(
                "A scoped customer identity must name the receiving channel account."
            )

    async def _existing(
        self, channel_identity: ChannelIdentity, organization_id: uuid.UUID
    ) -> ContactChannelIdentity | None:
        """The stored identity row, matched on exact identity or on the Lead.

        Both lookups are the *same* identity by two names — the platform's
        string and Product's row for it — so agreeing to either is not a guess.
        Nothing here matches on similarity.
        """
        found: ContactChannelIdentity | None = await self._session.scalar(
            select(ContactChannelIdentity)
            .where(ContactChannelIdentity.organization_id == organization_id)
            .where(ContactChannelIdentity.channel == channel_identity.channel)
            .where(
                ContactChannelIdentity.channel_account_id
                == channel_identity.channel_account_id
            )
            .where(
                (ContactChannelIdentity.identity == channel_identity.identity)
                | (ContactChannelIdentity.lead_id == channel_identity.lead_id)
            )
            .order_by(ContactChannelIdentity.first_seen_at)
            .limit(1)
        )
        return found

    async def _refresh_display_name(
        self, identity: ContactChannelIdentity, channel_identity: ChannelIdentity
    ) -> None:
        """Fill in a missing display hint; never overwrite one an operator set.

        A provider profile name is only a sender-controlled hint. It is useful
        when Product knows nothing else and must not replace a name a human
        recorded.
        """
        if not channel_identity.display_name:
            return
        contact = await self._session.get(Contact, identity.contact_id)
        if contact is not None and not contact.display_name:
            contact.display_name = channel_identity.display_name
