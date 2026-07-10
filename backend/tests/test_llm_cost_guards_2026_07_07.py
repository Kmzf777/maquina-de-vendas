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
    # Núcleo nativo (migração 09/07): a saída FATURADA (visível + thinking) vem de
    # usage_metadata.billed_output_tokens — mesmo invariante do incidente 1-6/jul.
    from app.agent.gemini_client import parse_result
    parsed = parse_result(_fake_resp(candidates=50, thoughts=2000))
    assert parsed.usage_metadata.billed_output_tokens == 2050  # visível + thinking
    assert parsed.usage_metadata.thoughts_token_count == 2000
    assert parsed.usage_metadata.prompt_token_count == 100


def test_completion_tokens_sem_thoughts_inalterado():
    from app.agent.gemini_client import parse_result
    parsed = parse_result(_fake_resp(candidates=42, thoughts=0))
    assert parsed.usage_metadata.billed_output_tokens == 42
    assert parsed.usage_metadata.thoughts_token_count == 0


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
async def test_generate_with_retry_levanta_budget_error(monkeypatch):
    """Estourado o teto, _generate_with_retry levanta ANTES de chamar o provedor, e o erro
    é subclasse de LLMUnavailableError (reusa o fallback de handoff)."""
    from unittest.mock import AsyncMock
    from app.agent import orchestrator, budget_guard
    monkeypatch.setattr(budget_guard, "is_exceeded", lambda: True)
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 99.0)
    monkeypatch.setattr(budget_guard, "daily_cost_limit_usd", lambda: 10.0)

    boom = AsyncMock(side_effect=AssertionError("provedor NÃO deveria ser chamado com budget estourado"))
    monkeypatch.setattr(orchestrator, "generate", boom)

    with pytest.raises(orchestrator.LLMUnavailableError):
        await orchestrator._generate_with_retry(model="gemini-2.5-flash", contents=[])
    boom.assert_not_awaited()


# ── 3. Knob de thinking inicial ─────────────────────────────────────────────────

def test_initial_thinking_default_ligado(monkeypatch):
    from app.agent.orchestrator import _initial_thinking_off
    monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)
    assert _initial_thinking_off("gemini-2.5-flash") is False  # ligado = pensa na 1ª


def test_initial_thinking_desligado_por_env(monkeypatch):
    from app.agent.orchestrator import _initial_thinking_off
    monkeypatch.setenv("LLM_INITIAL_THINKING", "off")
    assert _initial_thinking_off("gemini-2.5-flash") is True


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
