"""Observabilidade de cache do Gemini + custo cache-aware (FinOps 08/07/2026).

O implicit caching do Gemini 2.5 desconta ~75% dos tokens de prefixo cacheado, mas o
`usage_metadata.cached_content_token_count` era DESCARTADO pela fachada — impossível medir
o hit-rate do reorder do prompt (a7a287e) e o custo gravado ficava SUPERESTIMADO nos hits
(budget_guard queimando teto que não foi gasto). Cobre:

  1. _parse_response captura cached_content_token_count em _Usage.cached_tokens.
  2. track_token_usage aplica o desconto de cache (token cacheado = 25% do preço de input).
  3. O insert em token_usage persiste thoughts_tokens e cached_tokens (colunas novas).
  4. Deploy antes da migração (colunas ausentes → PGRST204): fallback re-insere no formato
     legado sem as colunas novas — a linha nunca se perde.
  5. Fiação: summary / memory / follow-up / orchestrator repassam cached+reasoning ao tracker.
"""
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _fake_um(prompt=100, candidates=50, thoughts=0, cached=None):
    kwargs = dict(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
    )
    if cached is not None:
        kwargs["cached_content_token_count"] = cached
    um = types.SimpleNamespace(**kwargs)
    cand = types.SimpleNamespace(finish_reason=None, content=types.SimpleNamespace(parts=[]))
    return types.SimpleNamespace(candidates=[cand], usage_metadata=um)


class _FakeTable:
    """Captura payloads de insert; opcionalmente falha nos que contêm colunas novas."""

    def __init__(self, fail_on_new_columns=False):
        self.fail_on_new_columns = fail_on_new_columns
        self.inserted: list[dict] = []
        self._pending = None

    def insert(self, payload):
        self._pending = payload
        return self

    def execute(self):
        payload = self._pending
        if self.fail_on_new_columns and ("cached_tokens" in payload or "thoughts_tokens" in payload):
            raise Exception(
                "{'code': 'PGRST204', 'message': \"Could not find the 'cached_tokens' "
                "column of 'token_usage' in the schema cache\"}"
            )
        self.inserted.append(dict(payload))
        return types.SimpleNamespace(data=[payload])


class _FakeSupabase:
    def __init__(self, table: _FakeTable):
        self._table = table

    def table(self, name):
        assert name == "token_usage"
        return self._table


_PRICING = {"price_per_input_token": 0.0000003, "price_per_output_token": 0.0000025}


@pytest.fixture
def tracked(monkeypatch):
    """track_token_usage com pricing fixo e supabase fake; retorna a tabela de captura."""
    from app.agent import token_tracker
    table = _FakeTable()
    monkeypatch.setattr(token_tracker, "get_model_pricing", lambda m: dict(_PRICING))
    monkeypatch.setattr(token_tracker, "get_supabase", lambda: _FakeSupabase(table))
    return table


# ── 1. captura de cached_content_token_count na fachada ─────────────────────

def test_parse_response_captura_cached_tokens():
    from app.agent.gemini_native import _parse_response
    parsed = _parse_response(_fake_um(prompt=100, candidates=50, thoughts=10, cached=8000))
    assert parsed.usage.cached_tokens == 8000


def test_parse_response_sem_cached_metadata_zera():
    from app.agent.gemini_native import _parse_response
    parsed = _parse_response(_fake_um(prompt=100, candidates=50, thoughts=0, cached=None))
    assert parsed.usage.cached_tokens == 0


# ── 2. custo cache-aware ─────────────────────────────────────────────────────

def test_custo_com_desconto_de_cache(tracked):
    from app.agent.token_tracker import track_token_usage
    track_token_usage(
        lead_id="L1", stage="atacado", model="gemini-2.5-flash", call_type="response",
        prompt_tokens=10_000, completion_tokens=500,
        cached_tokens=8_000, reasoning_tokens=200,
    )
    row = tracked.inserted[0]
    # (10000-8000)*0.30/1M + 8000*0.30/1M*0.25 + 500*2.50/1M = 0.0006 + 0.0006 + 0.00125
    assert row["total_cost"] == pytest.approx(0.00245, abs=1e-9)


def test_custo_sem_cache_permanece_igual_ao_legado(tracked):
    from app.agent.token_tracker import track_token_usage
    track_token_usage(
        lead_id="L1", stage="atacado", model="gemini-2.5-flash", call_type="response",
        prompt_tokens=10_000, completion_tokens=500,
    )
    row = tracked.inserted[0]
    assert row["total_cost"] == pytest.approx(10_000 * 3e-7 + 500 * 2.5e-6, abs=1e-9)


def test_cached_maior_que_prompt_clampa(tracked):
    """Defensivo: nunca gerar parte cheia negativa se o provedor reportar cached > prompt."""
    from app.agent.token_tracker import track_token_usage
    track_token_usage(
        lead_id="L1", stage="atacado", model="gemini-2.5-flash", call_type="response",
        prompt_tokens=10_000, completion_tokens=0, cached_tokens=15_000,
    )
    row = tracked.inserted[0]
    assert row["total_cost"] == pytest.approx(10_000 * 3e-7 * 0.25, abs=1e-9)


# ── 3. persistência das colunas novas ────────────────────────────────────────

def test_insert_persiste_thoughts_e_cached(tracked):
    from app.agent.token_tracker import track_token_usage
    track_token_usage(
        lead_id="L1", stage="secretaria", model="gemini-2.5-flash", call_type="response",
        prompt_tokens=1_000, completion_tokens=100,
        cached_tokens=700, reasoning_tokens=42,
    )
    row = tracked.inserted[0]
    assert row["cached_tokens"] == 700
    assert row["thoughts_tokens"] == 42


# ── 4. fallback quando as colunas ainda não existem (deploy antes da migração) ──

def test_fallback_legado_quando_coluna_ausente(monkeypatch):
    from app.agent import token_tracker
    table = _FakeTable(fail_on_new_columns=True)
    monkeypatch.setattr(token_tracker, "get_model_pricing", lambda m: dict(_PRICING))
    monkeypatch.setattr(token_tracker, "get_supabase", lambda: _FakeSupabase(table))

    token_tracker.track_token_usage(
        lead_id="L1", stage="atacado", model="gemini-2.5-flash", call_type="response",
        prompt_tokens=1_000, completion_tokens=100, cached_tokens=800, reasoning_tokens=10,
    )
    assert len(table.inserted) == 1, "linha se perdeu no fallback"
    row = table.inserted[0]
    assert "cached_tokens" not in row and "thoughts_tokens" not in row
    # o resto da linha continua íntegro (inclusive o custo COM desconto de cache)
    assert row["prompt_tokens"] == 1_000
    assert row["total_cost"] == pytest.approx(
        200 * 3e-7 + 800 * 3e-7 * 0.25 + 100 * 2.5e-6, abs=1e-9
    )


# ── 5. fiação dos call sites ─────────────────────────────────────────────────

def _usage_ns(prompt=100, completion=10, cached=60, reasoning=5):
    return types.SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        cached_tokens=cached, reasoning_tokens=reasoning,
    )


def test_summary_repassa_cache_e_reasoning(monkeypatch):
    from app.agent import summary, token_tracker
    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    resp = types.SimpleNamespace(usage=_usage_ns(cached=60, reasoning=5))
    summary._track_summary_usage(resp, {"id": "L1", "stage": "atacado"}, "gemini-2.5-flash", "qualification_summary")
    assert seen["cached_tokens"] == 60
    assert seen["reasoning_tokens"] == 5


def test_memory_repassa_cache_e_reasoning(monkeypatch):
    from app.agent import memory_manager, token_tracker
    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    resp = types.SimpleNamespace(usage=_usage_ns(cached=33, reasoning=7))
    memory_manager._track_memory_usage(resp, "L1", "atacado", "gemini-2.5-flash-lite")
    assert seen["cached_tokens"] == 33
    assert seen["reasoning_tokens"] == 7


@pytest.mark.asyncio
async def test_followup_repassa_cache_e_reasoning(monkeypatch):
    from app.follow_up import scheduler
    seen = {}
    monkeypatch.setattr(scheduler, "track_token_usage", lambda **k: seen.update(k))

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "oi"
    resp.choices[0].finish_reason = "stop"
    resp.usage = _usage_ns(cached=90, reasoning=0)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(scheduler, "get_gemini_client", lambda *a, **k: client)

    await scheduler._generate_followup_message(
        [{"role": "user", "content": "oi"}], 2, lead_id="L1", stage="atacado",
    )
    assert seen["cached_tokens"] == 90
    assert seen["reasoning_tokens"] == 0


@pytest.mark.asyncio
async def test_orchestrator_inicial_repassa_cache_e_reasoning(monkeypatch):
    from app.agent import orchestrator
    seen = {}
    monkeypatch.setattr(orchestrator, "track_token_usage", lambda **k: seen.update(k))
    monkeypatch.setattr(orchestrator, "get_lead", lambda _id: {"id": "L1", "ai_enabled": True, "phone": "+55"})
    monkeypatch.setattr(orchestrator, "get_history", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator, "get_products_by_funnel", lambda *a, **k: "")
    monkeypatch.setattr(orchestrator, "get_tools_for_stage", lambda *_: [])

    msg = MagicMock()
    msg.content = "resposta"
    msg.tool_calls = None
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg, finish_reason="stop")]
    resp.usage = _usage_ns(prompt=30_000, completion=200, cached=25_000, reasoning=150)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(orchestrator, "_get_client", lambda _m: client)

    out = await orchestrator.run_agent(
        {"id": "c1", "stage": "secretaria", "leads": {"id": "L1"}}, "oi",
    )
    assert out == "resposta"
    assert seen["cached_tokens"] == 25_000
    assert seen["reasoning_tokens"] == 150
