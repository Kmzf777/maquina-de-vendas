import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_run_agent_usa_history_limit_20():
    """run_agent deve buscar no máximo 20 mensagens do histórico."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-001",
        "stage": "secretaria",
        "leads": {"id": "lead-001", "name": "Joao", "phone": "5511999990000"},
    }

    captured_limit = {}

    def fake_get_history(conv_id, limit=30):
        captured_limit["limit"] = limit
        return []

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(tool_calls=None, content="oi"))]
    mock_response.usage = None

    with patch("app.agent.orchestrator.get_history", side_effect=fake_get_history), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-001", "phone": "5511999990000", "human_control": False}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
        await run_agent(conversation, "oi")

    assert captured_limit.get("limit") == 20, (
        f"run_agent deveria usar limit=20, mas usou limit={captured_limit.get('limit')}"
    )
