"""TDD do fallback de handoff quando o LLM está fora (2026-07-01).

Antes: run_agent lançava (LLM fora) → processor caía em [AGENT FAILED] → return mudo;
o lead (ex.: Welita) recebia 'digitando…' e nada mais. Agora: LLMUnavailableError
aciona encaminhar_humano — o cartão de contato do João é disparado ao lead e a IA é
desativada — em vez do silêncio. Exceções não-LLM mantêm o comportamento antigo.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.orchestrator import LLMUnavailableError
from app.buffer import processor as P


@pytest.mark.asyncio
async def test_handle_llm_down_dispara_encaminhar_humano():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock(return_value="Lead encaminhado para Joao Bras")) as mock_exec:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_exec.assert_awaited_once()
    args, kwargs = mock_exec.await_args
    assert args[0] == "encaminhar_humano"
    assert args[1]["vendedor"] == "Joao Bras"
    assert kwargs["lead_id"] == "lead-1"
    assert kwargs["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_handle_llm_down_fail_soft_quando_handoff_falha():
    lead = {"id": "lead-1", "phone": "556484794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    # Handoff que explode NÃO pode propagar (nunca escala a falha).
    with patch("app.agent.tools.execute_tool", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await P._handle_llm_down(lead, "556484794946", conversation)  # não levanta


@pytest.mark.asyncio
async def test_alerta_llm_down_dispara_no_limiar_e_deduplica():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock()), \
         patch("app.buffer.processor._record_llm_failure", new=AsyncMock(return_value=3)), \
         patch("app.buffer.processor._fire_llm_down_alert") as mock_alert:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_alert.assert_called_once_with(3)


@pytest.mark.asyncio
async def test_alerta_llm_down_nao_dispara_abaixo_do_limiar():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock()), \
         patch("app.buffer.processor._record_llm_failure", new=AsyncMock(return_value=2)), \
         patch("app.buffer.processor._fire_llm_down_alert") as mock_alert:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_alert.assert_not_called()


def test_fire_llm_down_alert_deduplica_por_alerta_nao_resolvido(monkeypatch):
    # Alerta não-resolvido recente já existe → NÃO cria outro.
    class _Resp:  # noqa
        data = [{"id": "a1"}]

    class _Q:  # encadeamento fluente do supabase-py
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Resp()

    class _SB:
        def table(self, *a, **k): return _Q()

    monkeypatch.setattr("app.buffer.processor.get_supabase", lambda: _SB(), raising=False)
    calls = {"n": 0}
    monkeypatch.setattr("app.buffer.processor.create_system_alert",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1), raising=False)
    P._fire_llm_down_alert(3)
    assert calls["n"] == 0  # deduplicado
