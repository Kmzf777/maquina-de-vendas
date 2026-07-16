import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text


@pytest.mark.asyncio
async def test_run_agent_usa_history_limit_60():
    """run_agent deve buscar no máximo 60 mensagens do histórico (commit b7703cc: 20→60)."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-001",
        "stage": "secretaria",
        "leads": {"id": "lead-001", "name": "Joao", "phone": "5511999990000"},
    }

    captured = {}

    def fake_get_history(conv_id, limit=30, roles=None, char_budget=None):
        captured["limit"] = limit
        captured["roles"] = roles
        captured["char_budget"] = char_budget
        return []

    with patch("app.agent.orchestrator.get_history", side_effect=fake_get_history), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-001", "phone": "5511999990000", "human_control": False}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(return_value=fake_text("oi"))):
        await run_agent(conversation, "oi")

    assert captured.get("limit") == 60, (
        f"run_agent deveria usar limit=60, mas usou limit={captured.get('limit')}"
    )
    # FinOps P2 (12/07): system-rows filtradas na query + teto de chars do histórico.
    assert captured.get("roles") == ("user", "assistant")
    assert captured.get("char_budget") and captured["char_budget"] > 0
