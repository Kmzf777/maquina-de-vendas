"""Testes itens 2 e 3 — cliente ativo não vira perdido; sem handoff redundante."""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock


# --- Item 2: registrar_sem_interesse_atual não marca cliente ativo como perdido ---

def test_motivo_indica_cliente():
    from app.agent.tools import _motivo_indica_cliente
    assert _motivo_indica_cliente("Lead ja e cliente e nao tem demanda no momento") is True
    assert _motivo_indica_cliente("já trabalho com os cafés de vocês") is True
    assert _motivo_indica_cliente("achou caro, vai pensar") is False


@pytest.mark.asyncio
async def test_sem_interesse_cliente_ativo_nao_marca_perdido():
    """Cliente ativo (motivo indica) → não seta stage=perdido nem move deal."""
    from app.agent import tools

    with patch.object(tools, "lead_has_active_relationship", return_value=False), \
         patch.object(tools, "update_lead") as mock_update, \
         patch.object(tools, "move_lead_deals_to_perdido") as mock_move_perdido, \
         patch.object(tools, "cancel_followups_by_phone"), \
         patch.object(tools, "append_lead_observation"), \
         patch.object(tools, "save_message"):
        out = await tools.execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "Lead ja e cliente e nao tem demanda no momento"},
            "L1", "5511999", "conv-1",
        )

    # NÃO marcou perdido / NÃO moveu deal
    mock_move_perdido.assert_not_called()
    kwargs = mock_update.call_args.kwargs
    assert kwargs.get("stage") != "perdido"
    assert "stage" not in kwargs  # só ai_enabled/opt_out
    assert kwargs.get("ai_enabled") is False
    assert "mantida no funil" in out


@pytest.mark.asyncio
async def test_sem_interesse_lead_frio_marca_perdido():
    """Lead frio (sem sinal de cliente) → fluxo normal: stage=perdido + move deal."""
    from app.agent import tools

    with patch.object(tools, "lead_has_active_relationship", return_value=False), \
         patch.object(tools, "update_lead") as mock_update, \
         patch.object(tools, "move_lead_deals_to_perdido") as mock_move_perdido, \
         patch.object(tools, "cancel_followups_by_phone"), \
         patch.object(tools, "append_lead_observation"), \
         patch.object(tools, "save_message"):
        out = await tools.execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "achou caro vs fornecedor atual, vai reavaliar no proximo trimestre"},
            "L2", "5511888", "conv-2",
        )

    mock_move_perdido.assert_called_once()
    assert mock_update.call_args.kwargs.get("stage") == "perdido"
    assert "sem interesse atual" in out.lower()


@pytest.mark.asyncio
async def test_sem_interesse_cliente_por_relacionamento_ativo():
    """Mesmo com motivo neutro, relacionamento ativo no CRM evita marcar perdido."""
    from app.agent import tools

    with patch.object(tools, "lead_has_active_relationship", return_value=True), \
         patch.object(tools, "update_lead") as mock_update, \
         patch.object(tools, "move_lead_deals_to_perdido") as mock_move_perdido, \
         patch.object(tools, "cancel_followups_by_phone"), \
         patch.object(tools, "append_lead_observation"), \
         patch.object(tools, "save_message"):
        await tools.execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "agora nao precisa"},
            "L3", "5511777", "conv-3",
        )

    mock_move_perdido.assert_not_called()
    assert "stage" not in mock_update.call_args.kwargs


# --- Item 3: prompt proíbe handoff redundante a cliente já conectado ---

def test_base_prompt_proibe_handoff_redundante():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Jessica", None, datetime(2026, 6, 22, 14, 0))
    assert "CLIENTE JA CONECTADO AO TIME" in s
    assert "PROIBIDO HANDOFF/CARTAO REDUNDANTE" in s
