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
from unittest.mock import AsyncMock, patch, MagicMock


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


# --- Falha 3: contexto outbound de 1º turno com a abertura no histórico ---

def _mock_openai_response(text: str = "resposta da ia"):
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _capture_messages(create_mock):
    call_args = create_mock.call_args_list[0]
    return call_args.kwargs.get("messages") or call_args.args[0]


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

    create_mock = AsyncMock(return_value=_mock_openai_response())
    with patch("app.agent.orchestrator.get_lead", return_value={
                "id": "lead-real", "name": "Maria", "phone": "5511900000099", "ai_enabled": True,
            }), \
         patch("app.agent.orchestrator.get_history", return_value=[opener]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "sim", lead_context=None, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    # system + assistant(opener) + user(contexto outbound) + user("sim")
    ctx_msgs = [m for m in messages if m["role"] == "user" and "O lead está respondendo" in m["content"]]
    assert len(ctx_msgs) == 1, messages
    assert "Falo com Maria neste número?" in ctx_msgs[0]["content"]
    assert messages[-1] == {"role": "user", "content": "sim"}


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

    create_mock = AsyncMock(return_value=_mock_openai_response())
    with patch("app.agent.orchestrator.get_lead", return_value={
                "id": "lead-real2", "name": "Maria", "phone": "5511900000098", "ai_enabled": True,
            }), \
         patch("app.agent.orchestrator.get_history", return_value=history), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "quero saber mais", lead_context=None, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    assert not any("O lead está respondendo" in str(m) for m in messages)
