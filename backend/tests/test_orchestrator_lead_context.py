import pytest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_mudar_stage_persiste_previous_stage_em_metadata():
    """Quando mudar_stage é chamada, orchestrator deve persistir previous_stage no lead.metadata."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-mudar",
        "stage": "secretaria",
        "leads": {
            "id": "lead-mudar",
            "phone": "5511999990000",
            "stage": "secretaria",
            "human_control": False,
            "metadata": {},
        },
    }

    # Use SimpleNamespace to avoid MagicMock treating 'name' as a special param
    func = SimpleNamespace(name="mudar_stage", arguments=json.dumps({"stage": "atacado"}))
    tc = SimpleNamespace(id="tc-1", function=func)

    tool_call_msg = MagicMock()
    tool_call_msg.tool_calls = [tc]
    tool_call_msg.content = None
    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=tool_call_msg)]
    resp1.usage = None

    text_msg = MagicMock()
    text_msg.tool_calls = None
    text_msg.content = "Oi, fala sobre atacado"
    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=text_msg)]
    resp2.usage = None

    update_lead_calls = []

    def fake_update_lead(lead_id, **fields):
        update_lead_calls.append({"lead_id": lead_id, "fields": fields})
        return {}

    # update_conversation and save_message are called from tools.py (execute_tool), not orchestrator
    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-mudar", "phone": "5511999990000",
            "human_control": False, "stage": "secretaria", "metadata": {},
         }), \
         patch("app.agent.orchestrator.update_lead", side_effect=fake_update_lead), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator._get_client") as mock_client, \
         patch("app.agent.tools.update_conversation", return_value={}), \
         patch("app.agent.tools.save_message", return_value={}), \
         patch("app.agent.tools.update_lead", return_value={}):

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])
        await run_agent(conversation, "quero comprar cafe")

    metadata_calls = [c for c in update_lead_calls if "metadata" in c["fields"]]
    assert len(metadata_calls) >= 1, "update_lead deveria ter sido chamado com metadata"
    metadata_saved = metadata_calls[0]["fields"]["metadata"]
    assert metadata_saved.get("previous_stage") == "secretaria", (
        f"previous_stage deveria ser 'secretaria', mas foi: {metadata_saved}"
    )
