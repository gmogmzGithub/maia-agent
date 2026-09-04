"""Make customer messaging channel-aware for Messenger and Instagram.

Revision ID: 0030_meta_channels
Revises: 0029_brand_config
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0030_meta_channels"
down_revision: str | None = "0029_brand_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANNELS = "'WhatsApp', 'FacebookMessenger', 'Instagram'"


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'WhatsApp'"),
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "channel_account_id",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.alter_column("leads", "wa_id", type_=sa.String(length=120))
    op.execute(
        sa.text(
            "UPDATE leads AS l SET channel_account_id = COALESCE(("
            "SELECT c.phone_number_id FROM conversations AS c "
            "WHERE c.lead_id = l.id ORDER BY c.created_at, c.id LIMIT 1"
            "), '')"
        )
    )
    op.drop_constraint("uq_leads_org_wa_id", "leads", type_="unique")
    op.create_check_constraint("ck_leads_channel", "leads", f"channel IN ({CHANNELS})")
    op.create_unique_constraint(
        "uq_leads_org_channel_identity",
        "leads",
        ["organization_id", "channel", "channel_account_id", "wa_id"],
    )

    op.add_column(
        "conversations",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'WhatsApp'"),
        ),
    )
    op.alter_column("conversations", "phone_number_id", type_=sa.String(length=200))
    op.create_check_constraint(
        "ck_conversations_channel", "conversations", f"channel IN ({CHANNELS})"
    )

    op.add_column(
        "inbox_messages",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'WhatsApp'"),
        ),
    )
    op.alter_column("inbox_messages", "from_wa_id", type_=sa.String(length=120))
    op.drop_constraint("uq_inbox_org_wamid", "inbox_messages", type_="unique")
    op.create_check_constraint(
        "ck_inbox_messages_channel", "inbox_messages", f"channel IN ({CHANNELS})"
    )
    op.create_unique_constraint(
        "uq_inbox_org_channel_provider_message",
        "inbox_messages",
        ["organization_id", "channel", "wamid"],
    )

    op.add_column(
        "outbox_messages",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'WhatsApp'"),
        ),
    )
    op.alter_column("outbox_messages", "to_wa_id", type_=sa.String(length=120))
    op.create_check_constraint(
        "ck_outbox_messages_channel", "outbox_messages", f"channel IN ({CHANNELS})"
    )

    op.add_column(
        "contact_channel_identities",
        sa.Column(
            "channel_account_id",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE contact_channel_identities AS i "
            "SET channel_account_id = l.channel_account_id "
            "FROM leads AS l WHERE i.lead_id = l.id"
        )
    )
    op.drop_constraint(
        "ck_contact_identity_channel", "contact_channel_identities", type_="check"
    )
    op.create_check_constraint(
        "ck_contact_identity_channel",
        "contact_channel_identities",
        f"channel IN ({CHANNELS})",
    )
    op.drop_constraint(
        "ck_contact_identity_whatsapp_lead",
        "contact_channel_identities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_contact_identity_whatsapp_lead",
        "contact_channel_identities",
        "lead_id IS NOT NULL",
    )
    op.drop_constraint(
        "uq_contact_identity", "contact_channel_identities", type_="unique"
    )
    op.create_unique_constraint(
        "uq_contact_identity",
        "contact_channel_identities",
        ["organization_id", "channel", "channel_account_id", "identity"],
    )

    for table, constraint in (
        ("consent_records", "ck_consent_records_channel"),
        ("suppression_records", "ck_suppression_records_channel"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, f"channel IN ({CHANNELS})")

    op.drop_constraint(
        "ck_opportunity_origins_source", "opportunity_origins", type_="check"
    )
    op.create_check_constraint(
        "ck_opportunity_origins_source",
        "opportunity_origins",
        "source IN ('WhatsAppInbound', 'MessagingInbound', "
        "'WebsiteConversation', 'Referral', 'Campaign', 'AdvisorEntry', "
        "'LegacyBackfill')",
    )

    op.drop_constraint(
        "ck_secret_reference_provider", "organization_secret_references", type_="check"
    )
    op.create_check_constraint(
        "ck_secret_reference_provider",
        "organization_secret_references",
        "provider IN ('MetaWhatsApp', 'MetaBusiness', 'MetaMessenger', "
        "'MetaInstagram', 'GoogleCalendar', 'Telegram', 'EasyBroker')",
    )
    op.drop_constraint(
        "ck_channel_binding_kind", "organization_channel_bindings", type_="check"
    )
    op.create_check_constraint(
        "ck_channel_binding_kind",
        "organization_channel_bindings",
        "kind IN ('WhatsAppPhoneNumberId', 'WhatsAppBusinessAccountId', "
        "'FacebookPageId', 'InstagramAccountId', 'TelegramBotId', "
        "'PublicSiteHost')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "inbox_messages",
        "outbox_messages",
        "conversations",
        "leads",
        "contact_channel_identities",
        "consent_records",
        "suppression_records",
    ):
        non_whatsapp = connection.execute(
            sa.text(f"SELECT 1 FROM {table} WHERE channel <> 'WhatsApp' LIMIT 1")
        ).first()
        if non_whatsapp is not None:
            raise RuntimeError(
                "Cannot downgrade while Facebook Messenger or Instagram customer "
                "messages exist."
            )
    new_values = (
        (
            "organization_channel_bindings",
            "kind IN ('FacebookPageId', 'InstagramAccountId')",
        ),
        (
            "organization_secret_references",
            "provider IN ('MetaMessenger', 'MetaInstagram')",
        ),
        ("opportunity_origins", "source = 'MessagingInbound'"),
    )
    for table, predicate in new_values:
        found = connection.execute(
            sa.text(f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1")
        ).first()
        if found is not None:
            raise RuntimeError(
                "Cannot downgrade while Messenger or Instagram configuration "
                "or commercial provenance exists."
            )

    op.drop_constraint(
        "ck_channel_binding_kind", "organization_channel_bindings", type_="check"
    )
    op.create_check_constraint(
        "ck_channel_binding_kind",
        "organization_channel_bindings",
        "kind IN ('WhatsAppPhoneNumberId', 'WhatsAppBusinessAccountId', "
        "'TelegramBotId', 'PublicSiteHost')",
    )
    op.drop_constraint(
        "ck_secret_reference_provider", "organization_secret_references", type_="check"
    )
    op.create_check_constraint(
        "ck_secret_reference_provider",
        "organization_secret_references",
        "provider IN ('MetaWhatsApp', 'MetaBusiness', 'GoogleCalendar', "
        "'Telegram', 'EasyBroker')",
    )
    op.drop_constraint(
        "ck_opportunity_origins_source", "opportunity_origins", type_="check"
    )
    op.create_check_constraint(
        "ck_opportunity_origins_source",
        "opportunity_origins",
        "source IN ('WhatsAppInbound', 'WebsiteConversation', 'Referral', "
        "'Campaign', 'AdvisorEntry', 'LegacyBackfill')",
    )

    for table, constraint in (
        ("suppression_records", "ck_suppression_records_channel"),
        ("consent_records", "ck_consent_records_channel"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, "channel = 'WhatsApp'")

    op.drop_constraint(
        "uq_contact_identity", "contact_channel_identities", type_="unique"
    )
    op.create_unique_constraint(
        "uq_contact_identity",
        "contact_channel_identities",
        ["organization_id", "channel", "identity"],
    )
    op.drop_constraint(
        "ck_contact_identity_channel", "contact_channel_identities", type_="check"
    )
    op.create_check_constraint(
        "ck_contact_identity_channel", "contact_channel_identities", "channel = 'WhatsApp'"
    )
    op.drop_constraint(
        "ck_contact_identity_whatsapp_lead",
        "contact_channel_identities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_contact_identity_whatsapp_lead",
        "contact_channel_identities",
        "channel <> 'WhatsApp' OR lead_id IS NOT NULL",
    )
    op.drop_column("contact_channel_identities", "channel_account_id")

    op.drop_constraint("ck_outbox_messages_channel", "outbox_messages", type_="check")
    op.drop_column("outbox_messages", "channel")
    op.alter_column("outbox_messages", "to_wa_id", type_=sa.String(length=32))

    op.drop_constraint(
        "uq_inbox_org_channel_provider_message", "inbox_messages", type_="unique"
    )
    op.create_unique_constraint(
        "uq_inbox_org_wamid", "inbox_messages", ["organization_id", "wamid"]
    )
    op.drop_constraint("ck_inbox_messages_channel", "inbox_messages", type_="check")
    op.drop_column("inbox_messages", "channel")
    op.alter_column("inbox_messages", "from_wa_id", type_=sa.String(length=32))

    op.drop_constraint("ck_conversations_channel", "conversations", type_="check")
    op.drop_column("conversations", "channel")
    op.alter_column("conversations", "phone_number_id", type_=sa.String(length=40))

    op.drop_constraint("uq_leads_org_channel_identity", "leads", type_="unique")
    op.create_unique_constraint(
        "uq_leads_org_wa_id", "leads", ["organization_id", "wa_id"]
    )
    op.drop_constraint("ck_leads_channel", "leads", type_="check")
    op.drop_column("leads", "channel_account_id")
    op.drop_column("leads", "channel")
    op.alter_column("leads", "wa_id", type_=sa.String(length=32))
