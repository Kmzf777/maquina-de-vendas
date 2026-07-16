"""TDD: o ramo terminal [AGENT FAILED] deve encaminhar ao humano (2026-07-04).

Auditoria 04/07: um lead com IA LIGADA (Alessandro, 5566999975586) mandou "Bom dia"
e a Valéria não respondeu — ZERO token_usage no horário, um humano pegou 4h depois.
Causa: `_create_with_retry` relança 400/401 do Gemini crus; eles (e qualquer exceção
genérica) escapavam do `except LLMUnavailableError` e caíam no ramo terminal
`[AGENT FAILED]`, que só INCREMENTAVA o contador e, no limiar, disparava um alerta
llm_down SEM handoff (handoff_ativo=False) — o lead ficava no vácuo. Mesma assinatura
do apagão 01-02/07 ("400/401 relançado cru morria em silêncio").

Correção: o ramo terminal delega a `_handle_agent_exhausted`, que encaminha ao humano
pela MESMA rede do LLMUnavailableError (encaminhar_humano via `_handle_llm_down`).
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.buffer import processor as P


@pytest.mark.asyncio
async def test_agent_exhausted_encaminha_ao_humano():
    """Esgotadas as tentativas por exceção genérica → handoff (não silêncio)."""
    lead = {"id": "lead-1", "phone": "5566999975586"}
    conversation = {"id": "conv-1", "stage": "secretaria"}

    with patch.object(P, "_handle_llm_down", new=AsyncMock()) as m_down, \
         patch.object(P, "pop_interest_marked") as m_pi, \
         patch.object(P, "pop_quote_executed") as m_pq, \
         patch.object(P, "_update_last_msg") as m_upd:
        await P._handle_agent_exhausted(lead, "5566999975586", conversation)

    # O handoff ao humano é disparado com o MESMO contrato do LLMUnavailableError
    # (inbound_text propaga o texto do turno p/ a checagem de autoresponder, 08/07).
    # Wartime 10/07: exceção genérica não é exaustão de budget/quota → reason="transient"
    # (janela de parking curta, comportamento pré-wartime).
    m_down.assert_awaited_once_with(
        lead, "5566999975586", conversation, inbound_text=None, reason="transient",
    )
    # E o turno é encerrado limpando os flags do lead e atualizando last_msg.
    m_pi.assert_called_once_with("conv-1")
    m_pq.assert_called_once_with("conv-1")
    m_upd.assert_called_once_with("conv-1")


@pytest.mark.asyncio
async def test_agent_exhausted_fail_soft_quando_handoff_falha():
    """Se o handoff em si explode, o ramo terminal NÃO propaga (nunca escala a falha)."""
    lead = {"id": "lead-1", "phone": "5566999975586"}
    conversation = {"id": "conv-1"}

    with patch.object(P, "_handle_llm_down", new=AsyncMock(side_effect=RuntimeError("boom"))), \
         patch.object(P, "pop_interest_marked"), \
         patch.object(P, "pop_quote_executed"), \
         patch.object(P, "_update_last_msg"):
        # não deve levantar
        await P._handle_agent_exhausted(lead, "5566999975586", conversation)
