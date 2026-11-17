"""Acceptance and channel formatting remain testable without database reads."""

import uuid

import pytest

from harness.presentation.whatsapp import render_reply
from harness.replies.validation import ReplyFacts, validate_proposal


def test_reply_policy_rejects_known_name_and_foreign_visit_without_queries(django_assert_num_queries):
    own, foreign = uuid.uuid4(), uuid.uuid4()
    facts = ReplyFacts("website", "Ana", True, True, False, own)
    with django_assert_num_queries(0):
        with pytest.raises(ValueError, match="name is already known"):
            validate_proposal({
                "blocks": [{"kind": "text", "text": "¿Con quién tengo el gusto?"}],
                "continuity": {"purpose": "conocer al prospecto", "pending": {
                    "kind": "name", "subject": "nombre",
                }},
            }, [], facts)
        with pytest.raises(ValueError, match="conversation-owned"):
            validate_proposal({
                "blocks": [{"kind": "text", "text": "Revisa tu visita."},
                           {"kind": "visit", "proposal_id": str(foreign)}],
                "continuity": {"purpose": "confirmar", "pending": {
                    "kind": "visit_confirmation", "subject": "visita",
                }},
            }, [], facts)


@pytest.mark.parametrize("action,title", [
    ("create", "Confirmar visita"), ("move", "Reprogramar visita"), ("cancel", "Cancelar visita"),
])
def test_whatsapp_adapter_uses_authorized_snapshot_without_orm(action, title, django_assert_num_queries):
    proposal_id = str(uuid.uuid4())
    blocks = [{"kind": "text", "text": "¿Confirmamos?"},
              {"kind": "visit", "proposal_id": proposal_id}]
    visit = {"id": proposal_id, "action": action, "summary": "Casa · lunes a las 10"}
    with django_assert_num_queries(0):
        payload = render_reply(blocks, [], criteria={}, base_url="https://example.test", visit=visit)
        button = payload["interactive"]["action"]["buttons"][0]["reply"]
        assert button == {"id": "visit:" + proposal_id, "title": title}
        assert payload["interactive"]["body"]["text"] == "Casa · lunes a las 10\n\n¿Confirmamos?"
        with pytest.raises(ValueError, match="no longer available"):
            render_reply(blocks, [], criteria={}, base_url="https://example.test",
                         visit={**visit, "id": str(uuid.uuid4())})
        with pytest.raises(ValueError, match="1024"):
            render_reply([{ "kind": "text", "text": "x" * 1024}, blocks[1]], [],
                         criteria={}, base_url="https://example.test", visit=visit)
