"""Blindagem do funil de Consumo + observabilidade do toggle manual da IA — 2026-06-24.

Auditoria lead 5551991295543 (Thiago): a IA foi desligada por um toggle MANUAL do CRM
(PATCH /conversations/{id}/agent) que não deixava rastro no histórico — auditoria cega.
E o stage `consumo` tinha `registrar_sem_interesse_atual` na allowlist (varejo B2C não é
"lead perdido"). Estes testes travam as duas correções.
"""
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch


# --- A) Blindagem: consumo não pode auto-descartar -------------------------

def test_consumo_nao_tem_registrar_sem_interesse():
    from app.agent.tools import get_tools_for_stage
    names = {t["function"]["name"] for t in get_tools_for_stage("consumo")}
    assert "registrar_sem_interesse_atual" not in names, \
        "varejo B2C nunca vira 'lead perdido' — consumo não pode auto-descartar"
    # opt-out (lead pede pra parar) e handoff continuam sendo a saída legítima do consumo
    assert "registrar_optout" in names


def test_outros_stages_mantem_registrar_sem_interesse():
    """A remoção é cirúrgica: só o consumo. Atacado/private_label/etc. mantêm o descarte."""
    from app.agent.tools import get_tools_for_stage
    for stage in ("secretaria", "atacado", "private_label", "exportacao"):
        names = {t["function"]["name"] for t in get_tools_for_stage(stage)}
        assert "registrar_sem_interesse_atual" in names, f"{stage} perdeu o descarte indevidamente"


def test_consumo_prompt_inbound_proibe_encerramento_tool():
    from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
    low = CONSUMO_PROMPT.lower()
    assert "nao chame nenhuma ferramenta de encerramento" in low or \
           "não chame nenhuma ferramenta de encerramento" in low
    assert "duvida" in low and ("b2c" in low or "cafes" in low)


def test_consumo_prompt_outbound_proibe_encerramento_tool():
    from app.agent.prompts.valeria_outbound.consumo import CONSUMO_PROMPT
    low = CONSUMO_PROMPT.lower()
    assert "nao chame nenhuma ferramenta de encerramento" in low or \
           "não chame nenhuma ferramenta de encerramento" in low


# --- B) Observabilidade: toggle manual grava system message ----------------

@pytest.mark.asyncio
async def test_toggle_off_grava_system_message():
    from app.conversations import router as conv_router

    captured = {}

    def _save(conversation_id, lead_id, role, content, **kwargs):
        captured.update(conversation_id=conversation_id, lead_id=lead_id, role=role, content=content)
        return {"id": "m1"}

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        MagicMock(data={"id": "conv-1", "lead_id": "lead-1", "agent_profile_id": None,
                        "leads": {"id": "lead-1", "ai_enabled": False}})
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch.object(conv_router, "get_supabase", return_value=sb), \
         patch.object(conv_router, "save_message", side_effect=_save):
        await conv_router.update_conversation_agent(
            "conv-1", conv_router.AgentUpdate(ai_enabled=False),
        )

    assert captured.get("role") == "system"
    assert captured.get("conversation_id") == "conv-1"
    assert "desativada" in captured.get("content", "").lower()
    assert "operador" in captured.get("content", "").lower()


@pytest.mark.asyncio
async def test_toggle_on_grava_system_message():
    from app.conversations import router as conv_router

    captured = {}

    def _save(conversation_id, lead_id, role, content, **kwargs):
        captured.update(role=role, content=content)
        return {"id": "m1"}

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        MagicMock(data={"id": "conv-1", "lead_id": "lead-1", "agent_profile_id": None,
                        "leads": {"id": "lead-1", "ai_enabled": True}})
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch.object(conv_router, "get_supabase", return_value=sb), \
         patch.object(conv_router, "save_message", side_effect=_save):
        await conv_router.update_conversation_agent(
            "conv-1", conv_router.AgentUpdate(ai_enabled=True),
        )

    assert captured.get("role") == "system"
    assert "ativada" in captured.get("content", "").lower()


@pytest.mark.asyncio
async def test_toggle_apenas_profile_nao_grava_system_message():
    """Trocar só o agent_profile (sem mexer no ai_enabled) NÃO gera log de toggle de IA."""
    from app.conversations import router as conv_router

    calls = {"n": 0}

    def _save(*a, **k):
        calls["n"] += 1
        return {"id": "m1"}

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        MagicMock(data={"id": "conv-1", "lead_id": "lead-1", "agent_profile_id": "p2", "leads": {"id": "lead-1", "ai_enabled": True}})
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch.object(conv_router, "get_supabase", return_value=sb), \
         patch.object(conv_router, "save_message", side_effect=_save):
        await conv_router.update_conversation_agent(
            "conv-1", conv_router.AgentUpdate(agent_profile_id="p2"),
        )

    assert calls["n"] == 0
