from unittest.mock import patch

import pytest

from app.agent import tools
from app.agent.tool_registry import ToolContext
from app.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_qualificar_lead_saves_partial_score_evidence_for_atacado():
    """A missing atacado score save would leave explicitly learned data unscored."""
    with patch("app.agent.tools.get_lead", return_value={"metadata": {}, "stage": "atacado"}), \
         patch("app.agent.tools.update_lead"), patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_conversation_history", return_value=[{"role": "user", "content": "tenho uma cafeteria e quero trocar meu fornecedor", "wamid": "wamid-1", "created_at": "2026-09-22T10:00:00Z"}]), \
         patch("app.agent.tools.save_score_evidence") as save_score:
        await execute_tool("qualificar_lead", {
            "segment": "cafeteria", "supplier_reason": "replace",
            "evidence": {"segment": {"text": "cafeteria"}, "supplier_reason": {"text": "quero trocar meu fornecedor"}},
        }, lead_id="lead-score-1", phone="5511999990000", conversation_id="conv-score-1")
    assert save_score.call_args.kwargs["updates"] == {"segment": "cafeteria", "supplier_reason": "replace"}
    assert save_score.call_args.kwargs["evidence"]["supplier_reason"] == {
        "text": "quero trocar meu fornecedor", "wamid": "wamid-1", "created_at": "2026-09-22T10:00:00Z", "message_ref": "wamid-1",
    }
    assert save_score.call_args.kwargs["source"] == "live"


@pytest.mark.asyncio
async def test_qualificar_lead_does_not_save_score_for_non_atacado_stage():
    """Saving private-label evidence would contaminate the wholesale-only score list."""
    with patch("app.agent.tools.get_lead", return_value={"metadata": {}, "stage": "private_label"}), \
         patch("app.agent.tools.update_lead"), patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.save_score_evidence") as save_score:
        await execute_tool("qualificar_lead", {"segment": "cafeteria"}, lead_id="lead-score-2", phone="5511999990000")
    save_score.assert_not_called()


@pytest.mark.asyncio
async def test_qualificar_lead_keeps_september_handoff_gates_with_score_fields():
    """Score fields must not bypass finality, concrete-volume, or shown-price gates."""
    invoked = []

    async def invoke(name, args):
        invoked.append((name, args))
        return "handoff"

    with patch("app.agent.tools.get_lead", return_value={"metadata": {}, "stage": "atacado"}), \
         patch("app.agent.tools.update_lead"), patch("app.agent.tools.save_message"), \
         patch("app.agent.tools._preco_ja_mostrado", return_value=True), \
         patch("app.agent.tools.save_score_evidence"):
        result = await tools._t_qualificar_lead(ToolContext(
            args={"finalidade": "cafeteria", "volume": "30kg/mês", "segment": "cafeteria"},
            lead_id="lead-score-3", phone="5511999990000", conversation_id="conv-score-3", invoke=invoke,
        ))
    assert result == "handoff"
    assert [name for name, _ in invoked] == ["encaminhar_humano"]


@pytest.mark.asyncio
async def test_qualificar_lead_rejects_evidence_not_quoted_by_user():
    """An agent-written claim must not be stored as objective lead evidence."""
    with patch("app.agent.tools.get_lead", return_value={"metadata": {}, "stage": "atacado"}), \
         patch("app.agent.tools.update_lead"), patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_conversation_history", return_value=[{"role": "assistant", "content": "você quer trocar fornecedor"}]), \
         patch("app.agent.tools.save_score_evidence") as save_score:
        await execute_tool("qualificar_lead", {
            "supplier_reason": "replace", "evidence": {"supplier_reason": {"text": "quer trocar fornecedor"}},
        }, lead_id="lead-score-4", phone="5511999990000", conversation_id="conv-score-4")
    save_score.assert_not_called()


@pytest.mark.asyncio
async def test_qualificar_lead_rejects_quote_that_normalizes_to_empty():
    """Emoji-only evidence must not match every lead message through an empty substring."""
    with patch("app.agent.tools.get_lead", return_value={"metadata": {}, "stage": "atacado"}), \
         patch("app.agent.tools.update_lead"), patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_conversation_history", return_value=[{"role": "user", "content": "quero trocar fornecedor"}]), \
         patch("app.agent.tools.save_score_evidence") as save_score:
        await execute_tool("qualificar_lead", {
            "supplier_reason": "replace", "evidence": {"supplier_reason": {"text": "👀\u200b"}},
        }, lead_id="lead-score-5", phone="5511999990000", conversation_id="conv-score-5")
    save_score.assert_not_called()
