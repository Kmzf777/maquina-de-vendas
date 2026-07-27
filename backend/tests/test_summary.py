import pytest
from unittest.mock import AsyncMock, patch

from app.agent.summary import generate_qualification_summary
from tests.gemini_fakes import fake_text


def _patch_generate(response_text: str) -> "patch":
    return patch(
        "app.agent.summary.generate",
        new=AsyncMock(side_effect=[fake_text(response_text)]),
    )


def _user_text(m: AsyncMock) -> str:
    """Texto do turno de usuário enviado ao núcleo nativo (contents[0])."""
    return m.await_args.kwargs["contents"][0].parts[0].text


@pytest.mark.asyncio
async def test_empty_history_returns_fallback():
    with _patch_generate("irrelevante") as m_gen:
        result = await generate_qualification_summary([], {}, "gemini-2.5-flash")
    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "Nenhuma mensagem" in result
    m_gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_without_user_or_assistant_returns_fallback():
    history = [{"role": "system", "content": "stage alterado"}]
    with _patch_generate("irrelevante") as m_gen:
        result = await generate_qualification_summary(history, {}, "gemini-2.5-flash")
    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "sem mensagens relevantes" in result
    m_gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_calls_llm_and_returns_response():
    history = [
        {"role": "user", "content": "Quero comprar café"},
        {"role": "assistant", "content": "Qual é o seu interesse?"},
        {"role": "user", "content": "Atacado, minha empresa é Padaria XYZ"},
    ]
    lead = {"name": "Carlos", "stage": "atacado"}
    expected = "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n* **Nome do Lead:** Carlos"

    with _patch_generate(expected) as m_gen:
        result = await generate_qualification_summary(history, lead, "gemini-2.5-flash")

    assert result == expected
    assert m_gen.await_count == 1
    user_msg = _user_text(m_gen)
    assert "Carlos" in user_msg
    assert "atacado" in user_msg
    assert "[Lead]: Quero comprar café" in user_msg
    # o prompt de sistema vai como system_instruction nativo, fora dos contents
    assert "briefings de vendas" in m_gen.await_args.kwargs["system_instruction"]


@pytest.mark.asyncio
async def test_gemini_25_disables_thinking_and_has_token_headroom():
    """Regressão: o resumo era cortado em '26/06/' porque gemini-2.5-flash gastava o
    budget de saída pensando (max_tokens=700 sem desligar o thinking). Garante que a
    chamada desliga o thinking (knob nativo thinking_off → ThinkingConfig(thinking_budget=0))
    e tem folga de tokens, igual ao orchestrator."""
    history = [{"role": "user", "content": "Quero comprar café no atacado"}]

    with _patch_generate("## NOVO LEAD QUALIFICADO PELA VALÉRIA\n**Data/Hora:** 26/06/2026 11:59") as m_gen:
        await generate_qualification_summary(history, {"name": "João"}, "gemini-2.5-flash")

    kwargs = m_gen.await_args.kwargs
    assert kwargs["thinking_off"] is True
    assert kwargs["max_output_tokens"] >= 2048


@pytest.mark.asyncio
async def test_no_facade_kwargs_leak_into_native_call():
    """Herdeiro do teste 'non_gemini_does_not_send_reasoning_effort': na era da fachada,
    kwargs OpenAI-shape (reasoning_effort) vazando p/ modelos que os rejeitam davam 400.
    O núcleo nativo tem assinatura FECHADA — nada de reasoning_effort/response_format/
    max_tokens; o controle de thinking é exclusivamente o knob nativo thinking_off."""
    history = [{"role": "user", "content": "Interesse em private label"}]

    with _patch_generate("## NOVO LEAD QUALIFICADO PELA VALÉRIA") as m_gen:
        await generate_qualification_summary(history, {"name": "Ana"}, "gemini-2.5-flash")

    kwargs = m_gen.await_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert "response_format" not in kwargs
    assert "max_tokens" not in kwargs  # nome nativo: max_output_tokens


@pytest.mark.asyncio
async def test_llm_failure_returns_graceful_fallback():
    """Falha do LLM ainda devolve dossiê válido — mas com CONTEÚDO, não com um aviso de erro.

    Atualizado em 27/07/2026: a asserção anterior era `"Erro" in result`, codificando o texto
    "*Erro ao gerar resumo automático.*". Durante o apagão de `gemini-2.5-flash` (22/07 17:48
    em diante) isso foi o que 63 de 64 dossiês entregaram ao João — o vendedor recebia o lead
    sem saber sequer o que ele tinha pedido, embora o histórico estivesse todo em mãos. O
    fallback agora monta um briefing determinístico (ver `_fallback_briefing`), então o teste
    passa a exigir o oposto: nada de "Erro", e o que o lead escreveu presente.
    """
    lead = {"name": "Ana", "stage": "private_label"}

    with patch("app.agent.summary.generate", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await generate_qualification_summary(
            [{"role": "user", "content": "Interesse em private label"}],
            lead,
            "gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert "Erro" not in result
    assert "Ana" in result
    assert "Interesse em private label" in result
