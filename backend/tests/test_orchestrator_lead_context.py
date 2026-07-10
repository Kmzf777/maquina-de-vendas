import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


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
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=[
             fake_tool_call("mudar_stage", {"stage": "atacado"}),
             fake_text("Oi, fala sobre atacado"),
         ])), \
         patch("app.agent.tools.update_conversation", return_value={}), \
         patch("app.agent.tools.save_message", return_value={}), \
         patch("app.agent.tools.update_lead", return_value={}):
        await run_agent(conversation, "quero comprar cafe")

    metadata_calls = [c for c in update_lead_calls if "metadata" in c["fields"]]
    assert len(metadata_calls) >= 1, "update_lead deveria ter sido chamado com metadata"
    metadata_saved = metadata_calls[0]["fields"]["metadata"]
    assert metadata_saved.get("previous_stage") == "secretaria", (
        f"previous_stage deveria ser 'secretaria', mas foi: {metadata_saved}"
    )
