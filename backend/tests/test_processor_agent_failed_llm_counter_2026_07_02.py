"""TDD do ramo genérico [AGENT FAILED] (2026-07-02, atualizado 2026-07-04).

Apagão 01-02/07: run_agent falhou rápido 3× por turno com uma exceção genérica
(400/401 relançado cru pelo orchestrator, ou exceção pré-API) — não LLMUnavailableError.
O processor esgotava as _AGENT_MAX_ATTEMPTS tentativas e caía no `else` → log
"[AGENT FAILED]" → return silencioso.

Correção 07/02: passou a incrementar o contador Redis llm:consecutive_failures e
disparar o alerta llm_down. Correção 07/04 (auditoria — fantasma do Alessandro, IA
ligada e 4h sem resposta): o ramo terminal agora TAMBÉM encaminha ao humano, pela
MESMA rede do LLMUnavailableError (`_handle_agent_exhausted` → `_handle_llm_down` →
encaminhar_humano). Não há mais o ramo "só contador + alerta, sem handoff": 400/401 e
qualquer exceção genérica que esgote as tentativas viram handoff, nunca silêncio.
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
    """3 falhas esgotam as tentativas; contador retorna 3 (>= threshold) → alerta dispara.
    Como agora HÁ handoff automático (via _handle_llm_down), o alerta é gravado com
    handoff_ativo=True (default) — os leads REALMENTE estão sendo encaminhados."""
    with _agent_failed_scenario(record_failure_return=3) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_record.assert_awaited_once()
    mock_alert.assert_called_once_with(3)
    mock_exec.assert_awaited()  # encaminhar_humano disparado


@pytest.mark.asyncio
async def test_agent_failed_nao_dispara_alerta_abaixo_do_limiar():
    """Contador retorna 1 (< threshold) → alerta NÃO dispara, mas o contador é registrado."""
    with _agent_failed_scenario(record_failure_return=1) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_record.assert_awaited_once()
    mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_agent_failed_aciona_handoff_automatico():
    """Correção 07/04: o [AGENT FAILED] genérico agora ACIONA encaminhar_humano (mesma
    rede do LLMUnavailableError), fechando o fantasma silencioso — em vez de deixar o
    lead no vácuo (caso Alessandro, IA ligada e 4h sem resposta)."""
    with _agent_failed_scenario(record_failure_return=3) as (mock_record, mock_alert, mock_exec):
        await P.process_buffered_messages("5511999999999", "oi", "chan-uuid")
    mock_exec.assert_awaited()
    # A 1ª chamada é o handoff ao humano.
    args, kwargs = mock_exec.await_args_list[0]
    assert args[0] == "encaminhar_humano"


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
    # A falha do contador é engolida por _handle_llm_down (fail-soft) com este warning,
    # e o handoff ao humano ainda é tentado a seguir.
    assert "falha ao registrar/alertar contador" in caplog.text
