"""Gatilho B: mudar_stage agenda um refresh do Dossiê (fire-and-forget) — Camada de Memória."""
from unittest.mock import AsyncMock, patch

import pytest

from tests.gemini_fakes import fake_text, fake_tool_call


def _conversation():
    return {
        "id": "conv-1",
        "stage": "secretaria",
        "leads": {"id": "lead-1", "name": "Ana", "phone": "5511999999999", "ai_enabled": True},
    }


@pytest.mark.asyncio
async def test_mudar_stage_schedules_memory_refresh():
    from app.agent.orchestrator import run_agent

    responses = [
        fake_tool_call("mudar_stage", {"stage": "atacado"}),
        fake_text("show, vamos falar de atacado então"),
    ]

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-1", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead"), \
         patch("app.agent.orchestrator.execute_tool", new=AsyncMock(return_value="ok")), \
         patch("app.agent.orchestrator._schedule_memory_refresh") as sched, \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=responses)):
        result = await run_agent(_conversation(), "quero comprar em grande quantidade")

    assert result == "show, vamos falar de atacado então"
    sched.assert_called_once_with("lead-1")
