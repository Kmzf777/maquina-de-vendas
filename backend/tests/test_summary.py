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
    assert "Resumo da Qualificação" in result
    assert "Nenhuma mensagem" in result


@pytest.mark.asyncio
async def test_history_without_user_or_assistant_returns_fallback():
    history = [{"role": "system", "content": "stage alterado"}]
    client = _make_client("irrelevante")
    result = await generate_qualification_summary(history, {}, client, "gpt-4o-mini")
    assert "Resumo da Qualificação" in result
    assert "sem mensagens relevantes" in result


@pytest.mark.asyncio
async def test_calls_llm_and_returns_response():
    history = [
        {"role": "user", "content": "Quero comprar café"},
        {"role": "assistant", "content": "Qual é o seu interesse?"},
        {"role": "user", "content": "Atacado, minha empresa é Padaria XYZ"},
    ]
    lead = {"name": "Carlos", "stage": "atacado"}
    expected = "## Resumo da Qualificação\n\n**Interesse:** atacado"
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

    assert "Resumo da Qualificação" in result
    assert "Erro" in result
