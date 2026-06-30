"""Vazamento de tool_code no retry (lead 5567996264477): a rede deve cobrir o retry e o optout.

Falha real: 1a resposta = tool_code puro -> strip -> vazio -> retry reincidiu no tool_code ->
retornado cru (L719 nao sanitizava) -> vazou. Apos a centralizacao, o codigo cru NUNCA chega
ao cliente. A partir de 2026-06-30 (Change C), o turno generico vazio NAO aborta mais em
silencio: devolve o fallback generico honesto (_SAFETY_FALLBACK_GENERIC) em vez de "". O
invariante critico permanece: o texto entregue jamais contem 'tool_code' nem 'default_api'.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_LEAK = "<tool_code> print(default_api.salvar_nome(nome='João Paulo Nogueira Alves')) </tool_code>"


def _make_response(content, tool_calls=None):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _conversation():
    return {
        "id": "conv-jp",
        "stage": "secretaria",
        "leads": {"id": "lead-jp", "name": "Paulo João", "phone": "5567996264477", "ai_enabled": True},
    }


def _history():
    return [{
        "role": "user", "content": "Sim\nJOÃO PAULO NOGUEIRA ALVES", "stage": "secretaria",
        "created_at": "2026-06-27T13:40:03Z", "wamid": "wamid-jp",
        "quoted_wamid": None, "message_type": "text", "metadata": None,
    }]


@pytest.mark.asyncio
async def test_toolcode_leak_inicial_e_retry_devolve_fallback_generico():
    """tool_code puro na inicial E no retry → run_agent devolve o fallback genérico honesto
    (Change C, 2026-06-30), NUNCA a string crua nem "" (silêncio)."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC
    call_responses = [_make_response(content=_LEAK), _make_response(content=_LEAK)]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), "Sim\nJOÃO PAULO NOGUEIRA ALVES")

    assert result == _SAFETY_FALLBACK_GENERIC, (
        "turno genérico vazio deve cair no fallback honesto, não em silêncio (Change C)"
    )
    assert "tool_code" not in result
    assert "default_api" not in result
    assert idx["i"] == 2, "deve ter feito o retry"


@pytest.mark.asyncio
async def test_toolcode_leak_inicial_retry_limpo_recupera_texto():
    """Inicial vaza tool_code → strip vazio → retry traz texto humano limpo → usa o texto."""
    from app.agent.orchestrator import run_agent
    call_responses = [
        _make_response(content=_LEAK),
        _make_response(content="boa Paulo, prazer\n\nsua demanda é pro mercado brasileiro ou exportação?"),
    ]
    idx = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[idx["i"]]
        idx["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(_conversation(), "Sim\nJOÃO PAULO NOGUEIRA ALVES")

    assert result == "boa Paulo, prazer\n\nsua demanda é pro mercado brasileiro ou exportação?"
    assert "tool_code" not in result


@pytest.mark.asyncio
async def test_optout_com_tool_code_cai_no_fallback_estatico():
    """Se a despedida do optout vier como tool_code puro, o strip esvazia → fallback estático."""
    from app.agent.orchestrator import run_agent

    tc = MagicMock()
    tc.function.name = "registrar_optout"
    tc.function.arguments = json.dumps({"motivo": "clicou parar"})
    tc.id = "tc-1"
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = _LEAK  # despedida veio como tool_code
    msg.model_dump.return_value = {"role": "assistant", "content": _LEAK, "tool_calls": []}
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="ok"):
        mock_client.return_value.chat.completions.create = AsyncMock(return_value=resp)
        result = await run_agent(_conversation(), "para de me mandar mensagem")

    assert "tool_code" not in result
    assert "default_api" not in result
    assert result == "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
