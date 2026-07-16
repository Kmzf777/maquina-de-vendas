"""Trilha B / B1 — Gatilho determinístico de entrada por frase de prefill (auditoria 10/07).

A frase fixa de prefill de um anúncio ("Olá! Quero saber mais sobre ter a Marca Própria de
Café.") deveria mover o lead pro funil certo já na entrada, mas dependia do LLM chamar
mudar_stage — falhou em 1 de 4 leads (João Marcos preso em pending por 2 turnos, sem
catálogo). Aqui o efeito vira código determinístico:

- núcleo puro `match_prefill_stage` (igualdade da frase normalizada, nunca substring);
- helper reusável `apply_stage_transition` (mesmo efeito de mudar_stage, idempotente);
- integração no processor: aplica ANTES do agente e o turno já enxerga o funil novo.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer.prefill import match_prefill_stage


# --- B1.a matcher (núcleo puro) ------------------------------------------------

def test_frase_exata_original_casa_private_label():
    assert match_prefill_stage(
        "Olá! Quero saber mais sobre ter a Marca Própria de Café."
    ) == "private_label"


def test_variacoes_de_caixa_acento_pontuacao_espacos_casam():
    for txt in (
        "OLÁ! QUERO SABER MAIS SOBRE TER A MARCA PRÓPRIA DE CAFÉ",
        "ola! quero saber mais sobre ter a marca propria de cafe",
        "Olá!  Quero   saber mais sobre ter a Marca Própria de Café",
        "  Olá! Quero saber mais sobre ter a Marca Própria de Café!!!  ",
        "Ola! Quero saber mais sobre ter a Marca Propria de Cafe.",
    ):
        assert match_prefill_stage(txt) == "private_label", txt


def test_substring_parcial_nao_casa():
    # A frase aparece EMBUTIDA numa mensagem maior — igualdade, não substring.
    assert match_prefill_stage(
        "vi um anuncio: Olá! Quero saber mais sobre ter a Marca Própria de Café. pode ajudar?"
    ) is None


def test_frase_diferente_nao_casa():
    assert match_prefill_stage("quero comprar cafe no atacado") is None
    assert match_prefill_stage("quero saber sobre marca propria") is None


def test_vazio_e_none_nao_casam():
    assert match_prefill_stage("") is None
    assert match_prefill_stage(None) is None


# --- B1.b apply_stage_transition (efeito canônico reusável) --------------------

def test_apply_stage_transition_grava_marcador_e_retorna_true():
    from app.agent import tools
    with patch.object(tools, "get_lead", return_value={"stage": "pending"}), \
         patch.object(tools, "get_conversation", return_value={"stage": "pending"}), \
         patch.object(tools, "update_conversation") as m_uconv, \
         patch.object(tools, "update_lead") as m_ulead, \
         patch.object(tools, "ensure_segment_deal") as m_deal, \
         patch.object(tools, "save_message") as m_save:
        applied = tools.apply_stage_transition("L1", "C1", "private_label")

    assert applied is True
    m_uconv.assert_called_once_with("C1", stage="private_label")
    m_ulead.assert_called_once_with("L1", stage="private_label")
    m_deal.assert_called_once_with("L1", "private_label")
    # Marcador system idêntico ao do executor mudar_stage (a transcrição realimenta o prompt).
    m_save.assert_called_once_with(
        "L1", "system", "stage alterado para: private_label", conversation_id="C1"
    )


def test_apply_stage_transition_idempotente_no_op():
    from app.agent import tools
    with patch.object(tools, "get_lead", return_value={"stage": "atacado"}), \
         patch.object(tools, "get_conversation", return_value={"stage": "atacado"}), \
         patch.object(tools, "update_conversation") as m_uconv, \
         patch.object(tools, "update_lead") as m_ulead, \
         patch.object(tools, "save_message") as m_save:
        applied = tools.apply_stage_transition("L1", "C1", "atacado")

    assert applied is False
    m_uconv.assert_not_called()
    m_ulead.assert_not_called()
    m_save.assert_not_called()


# --- B1.c integração no processor ---------------------------------------------

def _lead(stage):
    return {
        "id": "lead-1", "phone": "5511999990000", "stage": stage,
        "status": "active", "human_control": False, "metadata": None,
        "ai_enabled": True,
    }


def _conv(stage):
    return {
        "id": "conv-1", "stage": stage, "status": "active",
        "ai_enabled": True, "agent_profile_id": None,
    }


def _run_processor(lead_data, conv_data, combined_text, apply_mock):
    """Dirige process_buffered_messages capturando o stage visto por run_agent."""
    from app.buffer.processor import process_buffered_messages
    import asyncio

    captured = {}

    async def fake_run_agent(conv, text, lead_context=None, agent_profile_id=None):
        captured["stage"] = conv.get("stage")
        return "resposta"

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch-1", "agent_profiles": None}), \
         patch("app.buffer.processor.get_provider") as mock_prov, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.apply_stage_transition", side_effect=apply_mock) as m_apply, \
         patch("app.buffer.processor.run_agent", side_effect=fake_run_agent) as m_agent, \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["resposta"]):
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_prov.return_value.send_text = AsyncMock()
        asyncio.run(process_buffered_messages("+5511999990000", combined_text, channel_id="ch-1"))

    return captured, m_apply, m_agent


PREFILL = "Olá! Quero saber mais sobre ter a Marca Própria de Café."


def test_processor_pending_com_prefill_aplica_transicao_e_turno_ve_novo_stage():
    captured, m_apply, m_agent = _run_processor(
        _lead("pending"), _conv("pending"), PREFILL, apply_mock=lambda *a, **k: True,
    )
    m_apply.assert_called_once_with("lead-1", "conv-1", "private_label")
    # O turno atual já roda no funil novo (run_agent lê conversation["stage"]).
    assert captured["stage"] == "private_label"
    m_agent.assert_called_once()


def test_processor_stage_avancado_nao_aplica_prefill():
    captured, m_apply, m_agent = _run_processor(
        _lead("atacado"), _conv("atacado"), PREFILL, apply_mock=lambda *a, **k: True,
    )
    m_apply.assert_not_called()
    assert captured["stage"] == "atacado"


def test_processor_prefill_fail_open_segue_fluxo():
    def _boom(*a, **k):
        raise RuntimeError("db down")

    captured, m_apply, m_agent = _run_processor(
        _lead("pending"), _conv("pending"), PREFILL, apply_mock=_boom,
    )
    # Erro no gatilho não derruba o turno: o agente ainda roda (fail-open).
    m_agent.assert_called_once()
    assert captured["stage"] == "pending"
