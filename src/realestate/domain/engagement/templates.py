"""Meta-owned Message Template observations.

An Administrator may refresh provider truth but cannot approve a template.
Only an exact, recent ``Approved`` observation is consumable by the outbound
gate. A failed provider read leaves the prior rows untouched and therefore
cannot manufacture approval.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.clock import utc_now
from realestate.db.models import (
    ApprovedMessageTemplate,
    ConsentCategory,
    MessageTemplateStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, CommercialError

TEMPLATE_OBSERVATION_MAX_AGE = timedelta(hours=24)


class TemplateSourceUnavailable(CommercialError):
    message = "No fue posible verificar las plantillas actuales con Meta."


@dataclass(frozen=True)
class TemplateObservation:
    waba_id: str
    provider_template_id: str | None
    name: str
    language: str
    category: str
    status: str
    components: tuple[dict[str, object], ...]
    quality: str | None
    provider_api_version: str

    @property
    def checksum(self) -> str:
        encoded = json.dumps(
            self.components, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def body_text(self) -> str:
        for component in self.components:
            if str(component.get("type", "")).upper() == "BODY":
                return str(component.get("text", "")).strip()
        return ""


class TemplateSource(Protocol):
    @property
    def configured(self) -> bool: ...

    async def list_templates(self) -> tuple[TemplateObservation, ...]: ...


@dataclass(frozen=True)
class TemplateSyncResult:
    observed: int
    approved_marketing: int
    retired: int
    observed_at: datetime


@dataclass(frozen=True)
class ApprovedTemplateEvidence:
    name: str
    language: str
    category: ConsentCategory
    body_text: str
    observed_at: datetime


def _provider_status(raw: str) -> MessageTemplateStatus:
    value = raw.strip().upper()
    return {
        "APPROVED": MessageTemplateStatus.APPROVED,
        "PENDING": MessageTemplateStatus.PENDING,
        "REJECTED": MessageTemplateStatus.REJECTED,
        "PAUSED": MessageTemplateStatus.PAUSED,
        "DISABLED": MessageTemplateStatus.DISABLED,
        "DELETED": MessageTemplateStatus.DELETED,
        "ARCHIVED": MessageTemplateStatus.DELETED,
        "PENDING_DELETION": MessageTemplateStatus.DELETED,
    }.get(value, MessageTemplateStatus.DISABLED)


def _category(raw: str) -> ConsentCategory | None:
    try:
        return ConsentCategory(raw.strip().title())
    except ValueError:
        return None


class TemplateRegistry:
    """Persist and answer from Meta observations; exposes no local approve."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def synchronize(
        self,
        actor: Actor,
        source: TemplateSource,
        *,
        at: datetime | None = None,
    ) -> TemplateSyncResult:
        actor.require_administrator()
        moment = at or utc_now()
        if not source.configured:
            raise TemplateSourceUnavailable(
                "Faltan META_ACCESS_TOKEN o META_WABA_ID; no se verificó ninguna plantilla."
            )
        try:
            observations = await source.list_templates()
        except Exception as exc:
            raise TemplateSourceUnavailable() from exc

        identities: set[tuple[str, str]] = set()
        approved_marketing = 0
        for item in observations:
            name = item.name.strip()
            language = item.language.strip()
            if not name or not language or item.waba_id.strip() == "":
                continue
            identities.add((name, language))
            category = _category(item.category)
            status = _provider_status(item.status)
            row = await self._session.scalar(
                select(ApprovedMessageTemplate)
                .where(ApprovedMessageTemplate.organization_id == actor.organization_id)
                .where(ApprovedMessageTemplate.template_name == name)
                .where(ApprovedMessageTemplate.language_code == language)
                .with_for_update()
            )
            if row is None:
                row = ApprovedMessageTemplate(
                    organization_id=actor.organization_id,
                    waba_id=item.waba_id,
                    template_name=name,
                    language_code=language,
                    category=(category or ConsentCategory.SERVICE).value,
                    provider_status=status.value,
                    component_checksum=item.checksum,
                    provider_api_version=item.provider_api_version,
                    body_text=item.body_text,
                    source="MetaGraphAPI",
                    observed_at=moment,
                )
                self._session.add(row)
            row.waba_id = item.waba_id
            row.provider_template_id = item.provider_template_id
            row.category = (category or ConsentCategory.SERVICE).value
            row.provider_status = status.value
            row.body_text = item.body_text
            row.quality = item.quality
            row.component_checksum = item.checksum
            row.provider_api_version = item.provider_api_version
            row.observed_at = moment
            row.updated_at = moment
            row.retired_at = (
                None if status is MessageTemplateStatus.APPROVED else moment
            )
            if (
                status is MessageTemplateStatus.APPROVED
                and category is ConsentCategory.MARKETING
            ):
                approved_marketing += 1

        retired = 0
        existing = await self._session.scalars(
            select(ApprovedMessageTemplate)
            .where(ApprovedMessageTemplate.organization_id == actor.organization_id)
            .with_for_update()
        )
        for row in existing:
            if (row.template_name, row.language_code) not in identities:
                if row.provider_status != MessageTemplateStatus.DELETED.value:
                    retired += 1
                row.provider_status = MessageTemplateStatus.DELETED.value
                row.retired_at = moment
                row.observed_at = moment
                row.updated_at = moment

        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="SynchronizeMessageTemplates",
            subject_type="Organization",
            subject_id=str(actor.organization_id),
            details={
                "observed": len(observations),
                "approved_marketing": approved_marketing,
                "retired": retired,
            },
            commit=False,
        )
        await self._session.flush()
        return TemplateSyncResult(
            observed=len(observations),
            approved_marketing=approved_marketing,
            retired=retired,
            observed_at=moment,
        )

    async def approved(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        language: str | None,
        category: ConsentCategory,
        at: datetime,
    ) -> ApprovedTemplateEvidence | None:
        statement = (
            select(ApprovedMessageTemplate)
            .where(ApprovedMessageTemplate.organization_id == organization_id)
            .where(ApprovedMessageTemplate.template_name == name)
            .where(
                ApprovedMessageTemplate.provider_status
                == MessageTemplateStatus.APPROVED.value
            )
            .where(ApprovedMessageTemplate.retired_at.is_(None))
        )
        if language is not None:
            statement = statement.where(
                ApprovedMessageTemplate.language_code == language
            )
        rows = list(await self._session.scalars(statement.limit(2)))
        if len(rows) != 1:
            return None
        row = rows[0]
        if row.category != category.value:
            return None
        if at - row.observed_at > TEMPLATE_OBSERVATION_MAX_AGE:
            return None
        # Stage 7 has no template-parameter binding surface. Treating a
        # parameterized template as static would fail at Meta or leak braces.
        if "{{" in row.body_text or "}}" in row.body_text:
            return None
        return ApprovedTemplateEvidence(
            name=row.template_name,
            language=row.language_code,
            category=ConsentCategory(row.category),
            body_text=row.body_text,
            observed_at=row.observed_at,
        )
