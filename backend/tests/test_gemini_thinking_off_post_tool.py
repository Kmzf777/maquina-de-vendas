"""
Solução 2 (causa raiz do Bug 2): gemini-2.5-flash gasta o budget de saída "pensando"
após uma tool e devolve completion_tokens=0. A doc oficial do Gemini (OpenAI-compat)
permite desabilitar o thinking com reasoning_effort="none" — disponível para os modelos
2.5 (flash/flash-lite), MAS NÃO para 2.5-pro nem 3.x.

Aplicamos reasoning_effort="none" SOMENTE nas chamadas pós-tool (onde o texto ao cliente
precisa ser gerado), preservando o thinking na primeira chamada (escolha de tools).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Unit: _gemini_thinking_off(model)
# ---------------------------------------------------------------------------

def test_thinking_off_for_gemini_25_flash():
    from app.agent.orchestrator import _gemini_thinking_off
    assert _gemini_thinking_off("gemini-2.5-flash") == {"reasoning_effort": "none"}


def test_thinking_off_for_gemini_25_flash_lite():
    from app.agent.orchestrator import _gemini_thinking_off
    assert _gemini_thinking_off("gemini-2.5-flash-lite") == {"reasoning_effort": "none"}


def test_thinking_off_empty_for_gemini_25_pro():
    """2.5-pro não suporta reasoning_effort='none' — não devemos enviá-lo (evita 400)."""
    from app.agent.orchestrator import _gemini_thinking_off
    assert _gemini_thinking_off("gemini-2.5-pro") == {}


def test_thinking_off_empty_for_openai_model():
    from app.agent.orchestrator import _gemini_thinking_off
    assert _gemini_thinking_off("gpt-4o") == {}


# ---------------------------------------------------------------------------
# Integration: post-tool call carries reasoning_effort="none", first call does not
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: str = "{}", call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _make_response(content, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


@pytest.mark.asyncio
async def test_post_tool_call_disables_thinking_first_call_keeps_it():
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-think-001",
        "stage": "secretaria",
        "leads": {"id": "lead-t01", "name": "Renato", "phone": "5565996414453", "ai_enabled": True},
    }

    tool_call = _make_tool_call("mudar_stage", arguments='{"stage": "atacado"}', call_id="tc-think-001")

    # 1st → tool call ; 2nd (post-tool) → real text (no empty needed for this test)
    call_responses = [
        _make_response(content=None, tool_calls=[tool_call]),
        _make_response(content="Show! Você procura para revenda?", tool_calls=None),
    ]
    captured_kwargs = []

    async def fake_create(**kwargs):
        captured_kwargs.append(kwargs)
        return call_responses[len(captured_kwargs) - 1]

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "tenho cafeteria", "stage": "secretaria",
         "created_at": "2026-06-15T13:30:00Z", "wamid": "w", "quoted_wamid": None,
         "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-t01", "phone": "5565996414453", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead", new=MagicMock()), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="Stage alterado para: atacado")), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        await run_agent(conversation, "tenho cafeteria")

    assert len(captured_kwargs) == 2
    # First call: thinking preserved (no reasoning_effort)
    assert "reasoning_effort" not in captured_kwargs[0]
    # Second call (post-tool): thinking disabled
    assert captured_kwargs[1].get("reasoning_effort") == "none"
