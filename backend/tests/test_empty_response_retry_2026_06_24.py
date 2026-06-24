"""Recuperação de resposta vazia do LLM — auditoria leads 5549984064339 / 5551984772757, 2026-06-24.

Reincidência do bug da Carla: gemini-2.5-flash queima o budget pensando e devolve
completion_tokens=0 mesmo num input perfeitamente válido ("oi bom dia sim me chamo
Anderson"). A chamada inicial do run_agent NÃO desliga o thinking, então o turno normal
vazio caía direto no _SAFETY_FALLBACK_MESSAGE ("acho que sua mensagem chegou cortada aqui").

Comportamento desejado:
  1. resposta vazia → UM retry silencioso com thinking 100% off (recupera o texto real);
  2. se o retry trouxer texto → usa o texto (lead recebe resposta normal);
  3. se ainda vier vazio e não houver contexto coerente → aborta em silêncio (retorna ""),
     NUNCA o "chegou cortada".
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_response(content, tool_calls=None):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _conversation():
    return {
        "id": "conv-anderson",
        "stage": "secretaria",
        "leads": {"id": "lead-and", "name": "Anderson", "phone": "5551984772757", "ai_enabled": True},
    }


def _history():
    return [{
        "role": "user", "content": "oi bom dia sim me chamo Anderson", "stage": "secretaria",
        "created_at": "2026-06-24T12:38:38Z", "wamid": "wamid-a",
        "quoted_wamid": None, "message_type": "text", "metadata": None,
    }]


@pytest.mark.asyncio
async def test_empty_initial_then_retry_recovers_text():
    """Input válido, 1ª chamada vazia (gemini 0 tokens), retry sem thinking traz o texto real."""
    from app.agent.orchestrator import run_agent

    call_responses = [
        _make_response(content=""),                  # inicial — thinking on, 0 tokens
        _make_response(content="bom dia Anderson\n\nme conta o que te trouxe aqui"),  # retry off
    ]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-and", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), "oi bom dia sim me chamo Anderson")

    assert result == "bom dia Anderson\n\nme conta o que te trouxe aqui"
    assert idx["i"] == 2, "deve ter feito exatamente o retry silencioso"


@pytest.mark.asyncio
async def test_empty_initial_and_empty_retry_never_sends_chegou_cortada():
    """Os dois tiros vazios → aborta em silêncio. Garante que o texto literal do fallback
    enganoso NUNCA é devolvido."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MESSAGE

    call_responses = [_make_response(content=""), _make_response(content="")]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-and", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), "oi bom dia sim me chamo Anderson")

    assert result == ""
    assert result != _SAFETY_FALLBACK_MESSAGE
    assert "chegou cortada" not in result
