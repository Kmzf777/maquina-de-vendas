"""Tool escalar_reclamacao (auditoria 15/07, casos Aislan/Sirli).

Reclamação sobre o ATENDIMENTO HUMANO / pedido não entregue vira um ALERTA CRÍTICO à
gerência (create_system_alert) + carimbo no lead + cascata para o handoff formal com
despedida empática. Distinto da "reclamação de robô" (que é encaminhar_humano normal).
Fail-soft: nem o alerta nem o carimbo podem impedir o transbordo.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent import tools as T
from app.agent.tool_registry import ToolContext


@pytest.mark.asyncio
async def test_escalar_reclamacao_dispara_alerta_e_cascateia_handoff():
    fake_invoke = AsyncMock(return_value="Lead encaminhado para Joao Bras")
    ctx = ToolContext(
        args={"motivo": "fechou pedido ha meses e nunca recebeu; visualizam e nao respondem"},
        lead_id="lead-aislan", phone="5554999107411", conversation_id="conv-1",
        invoke=fake_invoke,
    )
    with patch.object(T, "create_system_alert") as mock_alert, \
         patch.object(T, "get_lead", return_value={"id": "lead-aislan", "name": "Aislan"}), \
         patch.object(T, "append_lead_observation") as mock_obs, \
         patch.object(T, "add_tags_to_lead") as mock_tags, \
         patch.object(T, "save_message"):
        result = await T._t_escalar_reclamacao(ctx)

    mock_alert.assert_called_once()
    assert mock_alert.call_args.kwargs["severity"] == "critical"
    assert mock_alert.call_args.kwargs["type"] == "lead_complaint_escalation"
    mock_obs.assert_called_once()
    mock_tags.assert_called_once_with("lead-aislan", ["escalonamento"])
    # Cascata para o handoff formal, marcada como escalonamento.
    fake_invoke.assert_awaited_once()
    cascaded_name, cascaded_args = fake_invoke.await_args.args
    assert cascaded_name == "encaminhar_humano"
    assert "ESCALONAMENTO" in cascaded_args["motivo"]
    assert cascaded_args["mensagem_despedida"]  # despedida empática (default) não-vazia
    assert result == "Lead encaminhado para Joao Bras"


@pytest.mark.asyncio
async def test_escalar_reclamacao_alerta_falhando_nao_impede_handoff():
    """create_system_alert levantando (Sentry/WhatsApp fora) → o transbordo ainda acontece."""
    fake_invoke = AsyncMock(return_value="ok-handoff")
    ctx = ToolContext(
        args={"motivo": "descaso, ninguem responde"},
        lead_id="l", phone="p", conversation_id="c", invoke=fake_invoke,
    )
    with patch.object(T, "create_system_alert", side_effect=RuntimeError("sentry fora")), \
         patch.object(T, "get_lead", return_value={"id": "l"}), \
         patch.object(T, "append_lead_observation"), \
         patch.object(T, "add_tags_to_lead"), \
         patch.object(T, "save_message"):
        result = await T._t_escalar_reclamacao(ctx)

    fake_invoke.assert_awaited_once()
    assert result == "ok-handoff"


@pytest.mark.asyncio
async def test_escalar_reclamacao_respeita_despedida_do_arg():
    fake_invoke = AsyncMock(return_value="ok")
    ctx = ToolContext(
        args={"motivo": "nao me entregaram", "mensagem_despedida": "o lote minimo e 100un; sinto muito, vou escalar"},
        lead_id="l", phone="p", conversation_id="c", invoke=fake_invoke,
    )
    with patch.object(T, "create_system_alert"), \
         patch.object(T, "get_lead", return_value={"id": "l"}), \
         patch.object(T, "append_lead_observation"), \
         patch.object(T, "add_tags_to_lead"), \
         patch.object(T, "save_message"):
        await T._t_escalar_reclamacao(ctx)

    _, cascaded_args = fake_invoke.await_args.args
    assert cascaded_args["mensagem_despedida"] == "o lote minimo e 100un; sinto muito, vou escalar"


def test_escalar_reclamacao_registrada_no_registry():
    tool = T.REGISTRY.get("escalar_reclamacao")
    assert tool is not None
    assert tool.effects.disables_ai is True
    assert "encaminhar_humano" in tool.effects.may_cascade_to
    # Não-consumo: o B2C nunca faz handoff, então não recebe o escalonamento.
    for st in ("secretaria", "atacado", "private_label", "exportacao"):
        assert st in tool.stages
    assert "consumo" not in tool.stages
