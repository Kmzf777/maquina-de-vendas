"""Fakes compartilhados p/ o núcleo Gemini nativo (migração 09/07/2026).

Receita de conversão dos testes antigos (fachada OpenAI → nativo):
  - `patch("app.agent.orchestrator._get_client")` + first_msg(.content/.tool_calls)
    → `patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=[...]))`
      com GenerateResult fakes daqui.
  - `_make_tool_call("x", {...})` no mock antigo → `fake_tool_call("x", {...})`.
  - asserts de nº de chamadas: `mock_client...create.call_count` → `m_gen.await_count`.
  - `finish_reason == "length"` → `== "MAX_TOKENS"` (vocabulário nativo).
Cada teste preserva a INTENÇÃO original (codificam incidentes reais de produção).
"""
from google.genai import types

from app.agent.gemini_client import FunctionCall, GenerateResult, UsageMetadata


def fake_usage(prompt=1000, out=50, thoughts=0, cached=0) -> UsageMetadata:
    return UsageMetadata(
        prompt_token_count=prompt, candidates_token_count=out,
        thoughts_token_count=thoughts, cached_content_token_count=cached,
    )


def fake_text(text: str | None, finish: str = "STOP", usage: UsageMetadata | None = None) -> GenerateResult:
    """Resultado só-texto (equivalente ao antigo first_msg.content sem tool_calls)."""
    content = types.Content(role="model", parts=[types.Part(text=text or "")])
    return GenerateResult(
        content=content, text=(text or None), function_calls=[],
        finish_reason=finish, usage_metadata=usage or fake_usage(),
    )


def fake_tool_call(
    name: str, args: dict, text: str | None = None,
    finish: str = "STOP", usage: UsageMetadata | None = None,
) -> GenerateResult:
    """Resultado com UMA chamada de função (e texto opcional junto)."""
    parts = []
    if text:
        parts.append(types.Part(text=text))
    parts.append(types.Part(function_call=types.FunctionCall(name=name, args=args)))
    return GenerateResult(
        content=types.Content(role="model", parts=parts),
        text=(text or None),
        function_calls=[FunctionCall(name=name, args=dict(args))],
        finish_reason=finish, usage_metadata=usage or fake_usage(),
    )


def fake_tool_calls(calls: list[tuple[str, dict]], text: str | None = None) -> GenerateResult:
    """Resultado com VÁRIAS chamadas de função no mesmo turno."""
    parts = [types.Part(text=text)] if text else []
    fcs = []
    for name, args in calls:
        parts.append(types.Part(function_call=types.FunctionCall(name=name, args=args)))
        fcs.append(FunctionCall(name=name, args=dict(args)))
    return GenerateResult(
        content=types.Content(role="model", parts=parts), text=(text or None),
        function_calls=fcs, finish_reason="STOP", usage_metadata=fake_usage(),
    )
