"""Loop-guard do ReAct: a chamada de fallback também é contabilizada (FinOps 08/07/2026).

Quando o modelo estoura MAX_TOOL_ITERATIONS, o guard dispara UMA última chamada text-only
(tools=None) para não deixar o lead mudo — era o único ponto do run_agent cujo usage era
DESCARTADO (gasto invisível). O turno patológico é justamente o mais caro (histórico cheio
reenviado N vezes), então ele precisa aparecer no token_usage com call_type próprio
("response_loopguard") para ser monitorável.
"""
from unittest.mock import AsyncMock

import pytest

from tests.gemini_fakes import fake_text, fake_tool_call, fake_usage


@pytest.mark.asyncio
async def test_loopguard_fallback_rastreado(monkeypatch):
    from app.agent import orchestrator

    tracked: list[dict] = []
    monkeypatch.setattr(orchestrator, "track_token_usage", lambda **k: tracked.append(k))
    monkeypatch.setattr(orchestrator, "get_lead", lambda _id: {"id": "L1", "ai_enabled": True, "phone": "+55"})
    monkeypatch.setattr(orchestrator, "get_history", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator, "get_products_by_funnel", lambda *a, **k: "")
    monkeypatch.setattr(
        orchestrator, "get_tools_for_stage",
        lambda *_: [{"name": "salvar_nome", "description": "", "parameters": {}}],
    )
    monkeypatch.setattr(orchestrator, "execute_tool", AsyncMock(return_value="ok"))

    async def fake_generate(**kwargs):
        # Com tools: devolve SEMPRE tool_call (força estourar MAX_TOOL_ITERATIONS).
        # Sem tools (chamada do loop-guard): devolve o texto de recuperação.
        if kwargs.get("tools") is None:
            return fake_text(
                "recuperado",
                usage=fake_usage(prompt=9000, out=30, thoughts=5, cached=7000),
            )
        return fake_tool_call("salvar_nome", {"name": "Zé"})

    monkeypatch.setattr(orchestrator, "generate", AsyncMock(side_effect=fake_generate))

    out = await orchestrator.run_agent(
        {"id": "c1", "stage": "secretaria", "leads": {"id": "L1"}}, "oi",
    )
    assert out == "recuperado"

    guard_rows = [t for t in tracked if t["call_type"] == "response_loopguard"]
    assert len(guard_rows) == 1, f"fallback do loop-guard não rastreado: {sorted({t['call_type'] for t in tracked})}"
    assert guard_rows[0]["prompt_tokens"] == 9000
    assert guard_rows[0]["cached_tokens"] == 7000
    assert guard_rows[0]["reasoning_tokens"] == 5
