import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.summary import generate_qualification_summary


def _make_client(response_text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = response_text
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)
    return client


@pytest.mark.asyncio
async def test_empty_history_returns_fallback():
    client = _make_client("irrelevante")
    result = await generate_qualification_summary([], {}, client, "gpt-4o-mini")
    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "Nenhuma mensagem" in result
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_history_without_user_or_assistant_returns_fallback():
    history = [{"role": "system", "content": "stage alterado"}]
    client = _make_client("irrelevante")
    result = await generate_qualification_summary(history, {}, client, "gpt-4o-mini")
    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "sem mensagens relevantes" in result
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_calls_llm_and_returns_response():
    history = [
        {"role": "user", "content": "Quero comprar café"},
        {"role": "assistant", "content": "Qual é o seu interesse?"},
        {"role": "user", "content": "Atacado, minha empresa é Padaria XYZ"},
    ]
    lead = {"name": "Carlos", "stage": "atacado"}
    expected = "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n* **Nome do Lead:** Carlos"
    client = _make_client(expected)

    result = await generate_qualification_summary(history, lead, client, "gemini-2.5-flash")

    assert result == expected
    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args
    messages_sent = call_kwargs.kwargs["messages"]
    user_msg = next(m for m in messages_sent if m["role"] == "user")
    assert "Carlos" in user_msg["content"]
    assert "atacado" in user_msg["content"]
    assert "[Lead]: Quero comprar café" in user_msg["content"]


@pytest.mark.asyncio
async def test_gemini_25_disables_thinking_and_has_token_headroom():
    """Regressão: o resumo era cortado em '26/06/' porque gemini-2.5-flash gastava o
    budget de saída pensando (max_tokens=700 sem reasoning_effort). Garante que a chamada
    desliga o thinking e tem folga de tokens, igual ao orchestrator."""
    history = [{"role": "user", "content": "Quero comprar café no atacado"}]
    client = _make_client("## NOVO LEAD QUALIFICADO PELA VALÉRIA\n**Data/Hora:** 26/06/2026 11:59")

    await generate_qualification_summary(history, {"name": "João"}, client, "gemini-2.5-flash")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs.get("reasoning_effort") == "none"
    assert kwargs["max_tokens"] >= 2048


@pytest.mark.asyncio
async def test_non_gemini_does_not_send_reasoning_effort():
    """Modelos OpenAI e gemini-2.5-pro/3.x rejeitam reasoning_effort='none' (400).
    Para esses, o kwarg NÃO deve ser enviado."""
    history = [{"role": "user", "content": "Interesse em private label"}]
    client = _make_client("## NOVO LEAD QUALIFICADO PELA VALÉRIA")

    await generate_qualification_summary(history, {"name": "Ana"}, client, "gpt-4o-mini")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_llm_failure_returns_graceful_fallback():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
    lead = {"name": "Ana", "stage": "private_label"}

    result = await generate_qualification_summary(
        [{"role": "user", "content": "Interesse em private label"}],
        lead,
        client,
        "gemini-2.5-flash",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "Erro" in result
