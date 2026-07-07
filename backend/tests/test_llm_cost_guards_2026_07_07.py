"""Blindagem de custo/observabilidade do LLM (incidente de estouro 1-6/jul/2026).

Cobre as quatro travas adicionadas:
  1. Contabilidade: thoughts_token_count (thinking) é SOMADO em completion_tokens.
  2. Kill-switch: teto diário de gasto bloqueia chamadas (fallback handoff) quando estourado.
  3. Knob de thinking inicial: LLM_INITIAL_THINKING=off desliga o thinking da 1ª chamada.
  4. Segregação de chave: rehearsal aborta se a chave Gemini de dev não for isolada da prod.
"""
import os
import types

import pytest


# ── 1. thoughts_token_count somado em completion_tokens ─────────────────────────

def _fake_resp(candidates: int, thoughts: int):
    um = types.SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
    )
    cand = types.SimpleNamespace(finish_reason=None, content=types.SimpleNamespace(parts=[]))
    return types.SimpleNamespace(candidates=[cand], usage_metadata=um)


def test_completion_tokens_inclui_thoughts():
    from app.agent.gemini_native import _parse_response
    parsed = _parse_response(_fake_resp(candidates=50, thoughts=2000))
    assert parsed.usage.completion_tokens == 2050  # visível + thinking
    assert parsed.usage.reasoning_tokens == 2000
    assert parsed.usage.prompt_tokens == 100


def test_completion_tokens_sem_thoughts_inalterado():
    from app.agent.gemini_native import _parse_response
    parsed = _parse_response(_fake_resp(candidates=42, thoughts=0))
    assert parsed.usage.completion_tokens == 42
    assert parsed.usage.reasoning_tokens == 0


# ── 2. Kill-switch de orçamento diário ──────────────────────────────────────────

def test_budget_desligado_quando_limite_zero(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.delenv("LLM_DAILY_COST_LIMIT_USD", raising=False)
    assert budget_guard.is_exceeded() is False  # sem env → desligado, sem tocar no banco


def test_budget_estourado_bloqueia(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 12.5)
    assert budget_guard.is_exceeded() is True


def test_budget_abaixo_do_teto_permite(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 3.0)
    assert budget_guard.is_exceeded() is False


@pytest.mark.asyncio
async def test_create_with_retry_levanta_budget_error(monkeypatch):
    """Estourado o teto, _create_with_retry levanta ANTES de chamar o provedor, e o erro
    é subclasse de LLMUnavailableError (reusa o fallback de handoff)."""
    from app.agent import orchestrator, budget_guard
    monkeypatch.setattr(budget_guard, "is_exceeded", lambda: True)
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 99.0)
    monkeypatch.setattr(budget_guard, "daily_cost_limit_usd", lambda: 10.0)

    class _BoomClient:  # se for chamado, falha o teste
        class chat:
            class completions:
                @staticmethod
                async def create(**_):
                    raise AssertionError("provedor NÃO deveria ser chamado com budget estourado")

    with pytest.raises(orchestrator.LLMUnavailableError):
        await orchestrator._create_with_retry(_BoomClient(), model="gemini-2.5-flash", messages=[])


# ── 3. Knob de thinking inicial ─────────────────────────────────────────────────

def test_initial_thinking_default_ligado(monkeypatch):
    from app.agent.orchestrator import _initial_thinking_kwargs
    monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)
    assert _initial_thinking_kwargs("gemini-2.5-flash") == {}  # ligado = sem reasoning_effort


def test_initial_thinking_desligado_por_env(monkeypatch):
    from app.agent.orchestrator import _initial_thinking_kwargs
    monkeypatch.setenv("LLM_INITIAL_THINKING", "off")
    assert _initial_thinking_kwargs("gemini-2.5-flash") == {"reasoning_effort": "none"}


# ── 4. Segregação de chave Gemini dev/prod ──────────────────────────────────────

def test_rehearsal_aborta_sem_chave_dev(monkeypatch):
    from scripts.rehearsal import gemini_actor
    monkeypatch.delenv("REHEARSAL_ALLOW_PROD", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_DEV", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "prod-key-xyz")
    with pytest.raises(SystemExit):
        gemini_actor.require_isolated_gemini_key()


def test_rehearsal_aborta_se_dev_igual_prod(monkeypatch):
    from scripts.rehearsal import gemini_actor
    monkeypatch.delenv("REHEARSAL_ALLOW_PROD", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "same-key")
    monkeypatch.setenv("GEMINI_API_KEY_DEV", "same-key")
    with pytest.raises(SystemExit):
        gemini_actor.require_isolated_gemini_key()


def test_rehearsal_ok_com_chave_dev_isolada(monkeypatch):
    from scripts.rehearsal import gemini_actor
    monkeypatch.delenv("REHEARSAL_ALLOW_PROD", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "prod-key")
    monkeypatch.setenv("GEMINI_API_KEY_DEV", "dev-key")
    gemini_actor.require_isolated_gemini_key()  # não levanta


def test_rehearsal_override_consciente(monkeypatch):
    from scripts.rehearsal import gemini_actor
    monkeypatch.setenv("REHEARSAL_ALLOW_PROD", "1")
    monkeypatch.delenv("GEMINI_API_KEY_DEV", raising=False)
    gemini_actor.require_isolated_gemini_key()  # override explícito → não levanta
