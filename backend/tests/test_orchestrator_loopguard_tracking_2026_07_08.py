"""Loop-guard do ReAct: a chamada de fallback também é contabilizada (FinOps 08/07/2026).

Quando o modelo estoura MAX_TOOL_ITERATIONS, o guard dispara UMA última chamada text-only
(tools=None) para não deixar o lead mudo — era o único ponto do run_agent cujo usage era
DESCARTADO (gasto invisível). O turno patológico é justamente o mais caro (histórico cheio
reenviado N vezes), então ele precisa aparecer no token_usage com call_type próprio
("response_loopguard") para ser monitorável.
"""
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        if exclude_none:
            d = {k: v for k, v in d.items() if v is not None}
        return d


def _tool_call(name="salvar_nome", args='{"name": "Zé"}'):
    return types.SimpleNamespace(
        id="call_0", function=types.SimpleNamespace(name=name, arguments=args),
    )


def _usage(prompt=1000, completion=20, cached=0, reasoning=0):
    return types.SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        cached_tokens=cached, reasoning_tokens=reasoning,
    )


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
        lambda *_: [{"type": "function", "function": {"name": "salvar_nome", "parameters": {}}}],
    )
    monkeypatch.setattr(orchestrator, "execute_tool", AsyncMock(return_value="ok"))

    async def fake_create(**kwargs):
        # Com tools: devolve SEMPRE tool_call (força estourar MAX_TOOL_ITERATIONS).
        # Sem tools (chamada do loop-guard): devolve o texto de recuperação.
        if kwargs.get("tools") is None:
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=_Msg(content="recuperado"), finish_reason="stop")],
                usage=_usage(prompt=9000, completion=30, cached=7000, reasoning=5),
            )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=_Msg(tool_calls=[_tool_call()]), finish_reason="tool_calls")],
            usage=_usage(),
        )

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=fake_create)
    monkeypatch.setattr(orchestrator, "_get_client", lambda _m: client)

    out = await orchestrator.run_agent(
        {"id": "c1", "stage": "secretaria", "leads": {"id": "L1"}}, "oi",
    )
    assert out == "recuperado"

    guard_rows = [t for t in tracked if t["call_type"] == "response_loopguard"]
    assert len(guard_rows) == 1, f"fallback do loop-guard não rastreado: {sorted({t['call_type'] for t in tracked})}"
    assert guard_rows[0]["prompt_tokens"] == 9000
    assert guard_rows[0]["cached_tokens"] == 7000
    assert guard_rows[0]["reasoning_tokens"] == 5
