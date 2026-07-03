"""TDD do contador llm_down no ramo genérico [AGENT FAILED] (2026-07-02).

Apagão 01-02/07: run_agent falhou rápido 3× por turno com uma exceção genérica
(400/401 relançado cru pelo orchestrator, ou exceção pré-API) — não LLMUnavailableError.
O processor esgotava as _AGENT_MAX_ATTEMPTS tentativas e caía no `else` → log
"[AGENT FAILED]" → return silencioso, SEM incrementar o contador Redis
llm:consecutive_failures nem disparar o alerta llm_down (que hoje só rodam no ramo
`except LLMUnavailableError`, via _handle_llm_down). Este teste fecha esse buraco de
observabilidade: mesmo contador/alerta do ramo LLMUnavailableError, MAS SEM handoff
automático — decisão de plano: o ramo genérico [AGENT FAILED] fica só com contador +
alerta; o handoff automático continua exclusivo de LLMUnavailableError.
"""
import logging
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.buffer import processor as P


def _make_channel():
    return {
        "id": "chan-uuid",
        "name": "Test",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "12345", "access_token": "tok"},
        "agent_profile_id": "profile-uuid",
        "agent_profiles": {
            "id": "profile-uuid", "model": "gpt-4.1",
            "base_prompt": "You are ValerIA", "stages": {},
        },
    }


@contextmanager
def _agent_failed_scenario(record_failure_return=0, record_failure_side_effect=None):
    """Dirige process_buffered_messages até o ramo [AGENT FAILED]: run_agent falha com
    um erro genérico (não-LLMUnavailableError) em TODAS as _AGENT_MAX_ATTEMPTS tentativas.

    Espelha os mocks de test_processor_errors.py::test_mensagem_do_usuario_sempre_salva_...
    (mesmo caminho até o [AGENT FAILED]) + asyncio.sleep mockado (sem os 2x5s de backoff)
    + os mocks de test_processor_llm_down_handoff_2026_07_01.py p/ contador/alerta/handoff.
    """
    if record_failure_side_effect is not None:
        mock_record = AsyncMock(side_effect=record_failure_side_effect)
    else:
        mock_record = AsyncMock(return_value=record_failure_return)

    with ExitStack() as stack:
        stack.enter_context(patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()))
        stack.enter_context(patch("app.buffer.processor.get_provider", return_value=AsyncMock()))
        stack.enter_context(patch("app.buffer.processor._resolve_media", return_value="oi"))
        stack.enter_context(patch("app.buffer.processor.get_or_create_lead",
                                   return_value={"id": "lead-1", "phone": "5511999999999"}))
        stack.enter_context(patch("app.buffer.processor.get_or_create_conversation", return_value={
            "id": "conv-1", "status": "active", "stage": "secretaria",
        }))
        stack.enter_context(patch("app.buffer.processor.save_message", return_value={}))
        stack.enter_context(patch("app.buffer.processor.run_agent",
                                   new=AsyncMock(side_effect=RuntimeError("boom"))))
        stack.enter_context(patch("app.buffer.processor.update_conversation", return_value={}))
        stack.enter_context(patch("app.buffer.processor.get_active_enrollment", return_value=None))
        stack.enter_context(patch("app.buffer.processor._is_recent_duplicate", return_value=False))
        stack.enter_context(patch("app.buffer.processor.get_supabase"))
        stack.enter_context(patch("app.buffer.processor._update_last_msg"))
        stack.enter_context(patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()))
        stack.enter_context(patch("app.buffer.processor._record_llm_failure", new=mock_record))
        mock_alert = stack.enter_context(patch("app.buffer.processor._fire_llm_down_alert"))
        mock_exec = stack.enter_context(patch("app.agent.tools.execute_tool", new=AsyncMock()))
        yield mock_record, mock_alert, mock_exec


@pytest.mark.asyncio
async def test_agent_failed_registra_contador_e_dispara_alerta_no_limiar():
    """3 falhas esgotam as tentativas; contador retorna 3 (>= threshold) → alerta dispara
    com handoff_ativo=False (Item 3 do review final): este ramo NUNCA aciona
    encaminhar_humano, então a mensagem do alerta não pode afirmar que os leads
    foram encaminhados automaticamente — ver test_agent_failed_nao_aciona_handoff_automatico."""
    with _agent_failed_scenario(record_failure_return=3) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_record.assert_awaited_once()
    mock_alert.assert_called_once_with(3, handoff_ativo=False)


@pytest.mark.asyncio
async def test_agent_failed_nao_dispara_alerta_abaixo_do_limiar():
    """Contador retorna 1 (< threshold) → alerta NÃO dispara, mas o contador é registrado."""
    with _agent_failed_scenario(record_failure_return=1) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_record.assert_awaited_once()
    mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_agent_failed_nao_aciona_handoff_automatico():
    """Diferença central vs. o ramo LLMUnavailableError: [AGENT FAILED] genérico NUNCA
    chama encaminhar_humano/execute_tool — só contador + alerta (decisão de plano)."""
    with _agent_failed_scenario(record_failure_return=3) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_agent_failed_fail_soft_quando_contador_explode(caplog):
    """Se _record_llm_failure lançar, process_buffered_messages NÃO propaga — fail-soft
    real — e loga um warning específico."""
    with _agent_failed_scenario(record_failure_side_effect=RuntimeError("redis down")) as (
        mock_record, mock_alert, mock_exec,
    ):
        with caplog.at_level(logging.WARNING, logger="app.buffer.processor"):
            await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")  # não deve levantar
    mock_alert.assert_not_called()
    assert "falha ao registrar contador pós-AGENT FAILED" in caplog.text
