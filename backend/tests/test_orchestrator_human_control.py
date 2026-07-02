from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_run_agent_bails_when_lead_has_human_control():
    """If the lead row shows human_control=True at the moment run_agent is invoked,
    the orchestrator must return '' and NEVER call the LLM — even if the processor
    somehow raced past its own check."""
    conversation = {
        "id": "conv-1",
        "lead_id": "lead-123",
        "stage": "atacado",
        "leads": {"id": "lead-123", "phone": "5511999990000", "stage": "atacado"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={
        "id": "lead-123",
        "phone": "5511999990000",
        "stage": "atacado",
        "human_control": True,
        "ai_enabled": False,
        "status": "converted",
    }) as mock_get, \
         patch("app.agent.orchestrator._get_gemini") as mock_gemini, \
         patch("app.agent.orchestrator.get_history", return_value=[]):
        from app.agent.orchestrator import run_agent
        result = await run_agent(conversation, "eai baoo?")

    assert result == ""
    mock_get.assert_called_once_with("lead-123")
    mock_gemini.assert_not_called()
