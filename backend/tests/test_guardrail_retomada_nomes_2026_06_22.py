"""Testes dos guardrails B/C/D (auditoria leads 5511946741676 e 5516993198700)."""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime


# --- B: retomar_contato_vendedor rebaixa p/ encaminhar_humano sem handoff prévio ---

def test_lead_had_prior_handoff_via_metadata():
    from app.agent.tools import _lead_had_prior_handoff
    assert _lead_had_prior_handoff("x", {"metadata": {"handoff_summary": "resumo"}}) is True
    assert _lead_had_prior_handoff("x", {"metadata": {"prior_handoff_joao": True}}) is True


@pytest.mark.asyncio
async def test_retomar_sem_handoff_rebaixa_para_encaminhar_humano():
    """Lead novo (sem handoff prévio) chamando retomar_contato_vendedor → fallback encaminhar_humano."""
    from app.agent import tools

    with patch.object(tools, "get_lead", return_value={"id": "L1", "metadata": {}, "phone": "5511999"}), \
         patch.object(tools, "_lead_had_prior_handoff", return_value=False), \
         patch.object(tools, "execute_tool", new_callable=AsyncMock, return_value="HANDOFF_OK") as mock_exec:
        result = await tools._retomar_contato_vendedor(
            {"motivo": "lead quer microlotes"}, "L1", "5511999", "conv-1"
        )

    assert result == "HANDOFF_OK"
    mock_exec.assert_awaited_once()
    args = mock_exec.await_args.args
    assert args[0] == "encaminhar_humano"
    assert args[1]["vendedor"] == "Joao Bras"
    assert "rebaixado de retomada" in args[1]["motivo"]


@pytest.mark.asyncio
async def test_retomar_com_handoff_previo_nao_rebaixa():
    """Com handoff prévio, a retomada segue o fluxo normal (não chama encaminhar_humano)."""
    from app.agent import tools

    with patch.object(tools, "get_lead", return_value={"id": "L2", "metadata": {"handoff_summary": "x"}, "phone": "5511888", "name": "Ana"}), \
         patch.object(tools, "_lead_had_prior_handoff", return_value=True), \
         patch.object(tools, "update_lead"), \
         patch.object(tools, "move_open_deal_for_handoff", return_value=True), \
         patch("app.follow_up.service.is_within_business_window", return_value=False), \
         patch.object(tools, "_safe_schedule_reengage", return_value=None), \
         patch.object(tools, "save_message"), \
         patch.object(tools, "execute_tool", new_callable=AsyncMock) as mock_exec:
        result = await tools._retomar_contato_vendedor(
            {"motivo": "retomar"}, "L2", "5511888", "conv-2"
        )

    mock_exec.assert_not_awaited()           # não rebaixou
    assert "DISPARO AGENDADO" in result


# --- C: prompt proíbe contradição de vendedor -----------------------------

def test_base_prompt_proibe_contradicao_de_vendedor():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Brunor", None, datetime(2026, 6, 22, 14, 0))
    assert "NOME DO VENDEDOR NA DESPEDIDA" in s
    assert "o Arthur vai te chamar" in s  # exemplo do anti-padrão citado


# --- D: sanitize rejeita lixo de importação -------------------------------

def test_sanitize_rejeita_lixo_de_import():
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name("João - Import - Leads Frios") is None
    assert sanitize_display_name("Fulano Import") is None
    assert sanitize_display_name("lead frio") is None


def test_sanitize_mantem_nomes_legitimos():
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name("João Silva") == "João Silva"
    assert sanitize_display_name("Maria Eduarda") == "Maria Eduarda"


def test_broadcast_token_lixo_import_vira_voce():
    from app.broadcast.worker import _lead_first_name, _lead_full_name
    assert _lead_full_name({"name": "João - Import - Leads Frios"}) == "você"
    assert _lead_first_name({"name": "Brunor_barista"}) == "você"
