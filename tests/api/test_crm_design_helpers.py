"""Pure rendering contracts for the dense CRM workflow components."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from realestate.api.crm import (
    OUTCOME_FORMS,
    _assignment_card,
    _exception_card,
    _history_card,
    _next_action_card,
    _outcome_form,
    _stage_card,
)
from realestate.db.models import (
    MemberRole,
    NextAction,
    NextActionKind,
    NextActionStatus,
    Opportunity,
    OpportunityAssignment,
    OpportunityException,
    OpportunityExceptionReason,
    OpportunityKind,
    OpportunityStage,
    OpportunityStageTransition,
    OrganizationMember,
)
from realestate.domain.commercial.actors import Actor, Authority, DuplicateCommand
from realestate.domain.commercial.organization import DirectoryPlan, parse_assignments


NOW = datetime(2026, 8, 29, 16, 42, tzinfo=UTC)


def _actor(*, administrator: bool = True) -> Actor:
    return Actor(
        organization_id=uuid.uuid4(),
        authority=(
            Authority.ADMINISTRATOR if administrator else Authority.ADVISOR
        ),
        member_id=uuid.uuid4(),
        label="persona@larevia.test",
        display_name="Valeria Montes" if administrator else "Mariana Torres",
        organization_name="Larevia",
    )


def _opportunity(actor: Actor, *, stage: OpportunityStage) -> Opportunity:
    return Opportunity(
        id=uuid.uuid4(),
        organization_id=actor.organization_id,
        contact_id=uuid.uuid4(),
        kind=OpportunityKind.DEMAND.value,
        stage=stage.value,
        responsible_advisor_id=actor.member_id,
        last_activity_at=NOW,
    )


def _advisor(actor: Actor) -> OrganizationMember:
    assert actor.member_id is not None
    return OrganizationMember(
        id=actor.member_id,
        organization_id=actor.organization_id,
        login=actor.label,
        display_name=actor.display_name,
        role=MemberRole.ADVISOR.value,
        advises=True,
        active=True,
    )


def test_active_workflow_components_render_current_work_and_history() -> None:
    actor = _actor()
    opportunity = _opportunity(actor, stage=OpportunityStage.NEW)
    advisor = _advisor(actor)
    action = NextAction(
        id=uuid.uuid4(),
        organization_id=actor.organization_id,
        opportunity_id=opportunity.id,
        responsible_member_id=advisor.id,
        kind=NextActionKind.CALL.value,
        due_at=NOW - timedelta(hours=1),
        note="Confirmar presupuesto",
        status=NextActionStatus.PENDING.value,
        created_at=NOW - timedelta(hours=2),
    )
    assignment = OpportunityAssignment(
        organization_id=actor.organization_id,
        opportunity_id=opportunity.id,
        advisor_id=advisor.id,
        basis="ManualAdmin",
        assigned_by=actor.label,
        assigned_at=NOW - timedelta(hours=3),
    )
    exception = OpportunityException(
        organization_id=actor.organization_id,
        opportunity_id=opportunity.id,
        reason=OpportunityExceptionReason.ADMIN_REVIEW.value,
        detail="Falta confirmar el límite.",
        recorded_by=actor.label,
        command_key="design-helper:exception",
        recorded_at=NOW,
    )
    transition = OpportunityStageTransition(
        organization_id=actor.organization_id,
        opportunity_id=opportunity.id,
        from_stage=None,
        to_stage=OpportunityStage.NEW.value,
        reason="OperatorDecision",
        detail="Oportunidad registrada.",
        actor_type="OrganizationMember",
        actor_id=actor.label,
        command_key="design-helper:transition",
        occurred_at=NOW,
    )

    next_action = _next_action_card(
        opportunity, action, True, [action], [advisor], actor, NOW
    )
    assert "Vencida" in next_action
    assert "Historial de acciones (1)" in next_action
    assert "Sustituir la siguiente acción" in next_action
    assert 'id="a-responsable"' in next_action

    stage = _stage_card(opportunity, actor)
    assert "Calificar y dejar seguimiento" in stage
    assert "Registrar como perdida" in stage

    assignment_html = _assignment_card(
        opportunity,
        actor,
        [advisor],
        {advisor.id: advisor.display_name},
        [assignment],
    )
    assert "Liberar y enviar a la cola" in assignment_html
    assert "Historial de asignaciones (1)" in assignment_html

    assert "Cerrar excepción" in _exception_card(opportunity, exception)
    assert "Registrar excepción" in _exception_card(opportunity, None)
    assert "Historial de etapas" in _history_card([transition])


def test_closed_and_advisor_variants_hide_or_explain_unavailable_work() -> None:
    administrator = _actor()
    advisor = _actor(administrator=False)
    closed = _opportunity(administrator, stage=OpportunityStage.WON)
    active_for_advisor = _opportunity(advisor, stage=OpportunityStage.NEGOTIATING)

    closed_actions = _next_action_card(
        closed, None, False, [], [], administrator, NOW
    )
    assert "no admite nuevas acciones" in closed_actions
    assert "No hay una siguiente acción vigente" in closed_actions
    assert "ya está cerrada" in _stage_card(closed, administrator)
    assert _exception_card(closed, None) == ""

    no_advisors = _assignment_card(closed, administrator, [], {}, [])
    assert "No hay asesores activos configurados" in no_advisors
    assert _assignment_card(active_for_advisor, advisor, [], {}, []) == ""
    assert "Sólo un administrador" in _stage_card(active_for_advisor, advisor)
    assert _history_card([]) == ""

    # Every consequential outcome keeps its specific evidence vocabulary.
    rendered = "".join(_outcome_form(active_for_advisor, form) for form in OUTCOME_FORMS)
    assert "Registrar pérdida" in rendered
    assert "Poner en pausa" in rendered
    assert "Registrar operación concluida" in rendered


def test_actor_and_directory_helpers_keep_configuration_explicit() -> None:
    assert parse_assignments(
        " asesor@larevia.test = calendar-1, roto, =vacio, sin-valor= "
    ) == {"asesor@larevia.test": "calendar-1"}

    plan = DirectoryPlan(
        administrators=("admin@larevia.test",),
        advisors=("asesor@larevia.test",),
        default_advisor="asesor@larevia.test",
        fallback_calendar_id="calendar-fallback",
    )
    assert plan.calendar_for("asesor@larevia.test") == "calendar-fallback"

    duplicate = DuplicateCommand("crm:test-replay")
    assert duplicate.command_key == "crm:test-replay"
    assert str(duplicate) == duplicate.message
