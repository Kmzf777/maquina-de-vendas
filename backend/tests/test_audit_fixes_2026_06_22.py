"""Testes das correções da auditoria 2026-06-22.

Cobre:
- Falha 1: fallback de segurança sem falsa promessa de retorno.
- Falha 3: contexto outbound de 1º turno volta a disparar quando a abertura
  (broadcast/followup) está no histórico — is_first_turn por ausência de 'user'
  e campaign_message derivado do próprio template enviado.
- Falha 4: regra anti-loop de pergunta de nome no base prompt.
- Falhas 7/8: regra de aquecer-antes-de-qualificar no prompt outbound.
"""
import pytest
from unittest.mock import AsyncMock, patch


# --- Falha 1: fallback sem falsa promessa --------------------------------

def test_safety_fallback_nao_promete_retorno_futuro():
    from app.agent.orchestrator import _SAFETY_FALLBACK_MESSAGE
    txt = _SAFETY_FALLBACK_MESSAGE.lower()
    # A regressão antiga prometia "já te respondo" / pedia "um segundinho" — promessa
    # que nunca se cumpria (não há processamento diferido).
    assert "segundinho" not in txt
    assert "já te respondo" not in txt and "ja te respondo" not in txt
    # Deve pedir reenvio por texto.
    assert "texto" in txt


# --- Falha 4 / 7-8: regras presentes nos prompts -------------------------

def test_base_prompt_tem_regra_anti_loop_nome():
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    s = build_base_prompt("Valdemar", None, datetime(2026, 6, 22, 14, 0))
    assert "ANTI-LOOP DE PERGUNTA DE NOME" in s


def test_outbound_prompt_tem_regra_aquecer_antes_de_qualificar():
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    assert "AQUECER ANTES DE QUALIFICAR" in SECRETARIA_PROMPT
    # Proíbe a triagem mercado/exportação como bolha pós-"Sim".
    assert "mercado brasileiro ou pra exportacao" in SECRETARIA_PROMPT


def test_base_prompt_tem_regra_cliente_existente():
    """Gap #6 (prompt): ambas as personas devem reconhecer lead que já é nosso cliente."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    s = build_base_prompt("Grazieli", None, datetime(2026, 6, 22, 14, 0))
    assert "JA E NOSSO CLIENTE" in s


def test_media_fallback_example_segue_humanizacao():
    """O exemplo de mídia não suportada não pode mais quebrar regra 22 / lowercase / '!'."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    s = build_base_prompt("Cris", None, datetime(2026, 6, 22, 14, 0))
    # Exemplo antigo robótico removido.
    assert "Oi! Acabei não conseguindo abrir" not in s
    # Novo exemplo, sem falsa promessa e em texto humanizado.
    assert "me manda por texto aqui que eu te ajudo na hora" in s


# --- Falha 3: contexto outbound de 1º turno com a abertura no histórico ---

from tests.gemini_fakes import fake_text


def _capture_contents(m_gen):
    """kwargs da PRIMEIRA chamada nativa: (contents, blob de todo o texto enviado).

    Migração 09/07 (Gemini 100% nativo): o turno viaja como kwargs["contents"]
    (list[types.Content]) + kwargs["system_instruction"] — não mais "messages".
    """
    kwargs = m_gen.await_args_list[0].kwargs
    contents = kwargs["contents"]
    texts = []
    for c in contents:
        for p in (c.parts or []):
            if getattr(p, "text", None):
                texts.append(p.text)
    return contents, " ".join(texts)


@pytest.mark.asyncio
async def test_outbound_injeta_contexto_com_abertura_no_historico():
    """Caso REAL: a abertura broadcast está no histórico e o lead acabou de responder.

    is_first_turn deve ser True (não há msg 'user' anterior) e o campaign_message
    deve ser derivado do próprio template enviado.
    """
    from app.agent.orchestrator import run_agent

    opener = {
        "role": "assistant",
        "content": "Olá, tudo bem? Aqui é a Valéria, da Café Canastra. Falo com Maria neste número?",
        "sent_by": "broadcast",
    }
    conversation = {
        "id": "conv-out-real",
        "stage": "secretaria",
        "leads": {"id": "lead-real", "name": "Maria", "phone": "5511900000099"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={
                "id": "lead-real", "name": "Maria", "phone": "5511900000099", "ai_enabled": True,
            }), \
         patch("app.agent.orchestrator.get_history", return_value=[opener]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gemini-2.5-flash"}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text("resposta da ia"))) as m_gen:
        await run_agent(conversation, "sim", lead_context=None, agent_profile_id="profile-out")

    contents, blob = _capture_contents(m_gen)
    # O contexto de 1º turno outbound tem que ser injetado. O texto foi reescrito para o arco
    # AIDA caloroso (commit 1674bc5) — marcador estavel = "PRIMEIRO turno" — e a abertura-template
    # e derivada do proprio broadcast no historico ("Falo com Maria neste número?").
    assert "PRIMEIRO turno" in blob, contents
    assert "Falo com Maria neste número?" in blob
    # A última entrada do turno continua sendo a mensagem atual do lead.
    assert contents[-1].role == "user"
    assert contents[-1].parts[0].text == "sim"


@pytest.mark.asyncio
async def test_outbound_segundo_turno_com_abertura_nao_injeta():
    """Já existe uma msg 'user' no histórico → não é mais 1º turno → não injeta."""
    from app.agent.orchestrator import run_agent

    history = [
        {"role": "assistant", "content": "Olá, Falo com Maria?", "sent_by": "broadcast"},
        {"role": "user", "content": "sim"},
        {"role": "assistant", "content": "show, cadastro confirmado", "sent_by": "agent"},
    ]
    conversation = {
        "id": "conv-out-real2",
        "stage": "secretaria",
        "leads": {"id": "lead-real2", "name": "Maria", "phone": "5511900000098"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={
                "id": "lead-real2", "name": "Maria", "phone": "5511900000098", "ai_enabled": True,
            }), \
         patch("app.agent.orchestrator.get_history", return_value=history), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gemini-2.5-flash"}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text("resposta da ia"))) as m_gen:
        await run_agent(conversation, "quero saber mais", lead_context=None, agent_profile_id="profile-out")

    _contents, blob = _capture_contents(m_gen)
    # 2º turno: NAO injeta o contexto de 1º turno outbound (marcador "PRIMEIRO turno" ausente)
    # — nem nos contents nem no system_instruction.
    assert "PRIMEIRO turno" not in blob
    assert "PRIMEIRO turno" not in (m_gen.await_args_list[0].kwargs.get("system_instruction") or "")
