"""Gatilho B: mudar_stage agenda um refresh do Dossiê (fire-and-forget) — Camada de Memória."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _text_response(content):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _tool_response(name, arguments):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = ""
    tc = MagicMock()
    tc.id = "tc1"
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    msg.tool_calls = [tc]
    msg.model_dump.return_value = {"role": "assistant", "content": "", "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


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
        _tool_response("mudar_stage", {"stage": "atacado"}),
        _text_response("show, vamos falar de atacado então"),
    ]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        r = responses[idx["i"]]
        idx["i"] += 1
        return r

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-1", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead"), \
         patch("app.agent.orchestrator.execute_tool", new=AsyncMock(return_value="ok")), \
         patch("app.agent.orchestrator._schedule_memory_refresh") as sched, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), "quero comprar em grande quantidade")

    assert result == "show, vamos falar de atacado então"
    sched.assert_called_once_with("lead-1")
