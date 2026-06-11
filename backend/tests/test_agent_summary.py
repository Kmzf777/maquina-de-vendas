# backend/tests/test_agent_summary.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_empty_history_returns_new_header():
    """Histórico vazio deve retornar mensagem com o novo cabeçalho, sem chamar LLM."""
    from app.agent.summary import generate_qualification_summary

    mock_client = MagicMock()
    result = await generate_qualification_summary(
        history=[],
        lead={"name": "Ana", "stage": "atacado"},
        client=mock_client,
        model="gemini-2.5-flash",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_full_history_llm_receives_motivo_and_handoff_at():
    """Com histórico, motivo e handoff_at devem aparecer no contexto enviado ao LLM."""
    from app.agent.summary import generate_qualification_summary

    mock_choice = MagicMock()
    mock_choice.message.content = (
        "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n"
        "**Data/Hora:** 11/06/2026 14:30\n\n"
        "* **Nome do Lead:** João Silva\n"
        "* **Interesse Principal:** Atacado\n"
        "* **Nível de Aquecimento:** Alto — lead com intenção de compra\n"
        "* **Cenário Atual / Dor:** Fornecedor atual sem qualidade\n"
        "* **Expectativa de Volume/Orçamento:** R$300\n"
        "* **Tom da Conversa:** Objetivo e direto\n"
        "* **Recomendação de Abordagem para o João:** Confirmar produto e fechar\n"
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    history = [
        {"role": "user", "content": "quero café para minha cafeteria"},
        {"role": "assistant", "content": "vou apresentar nossos produtos"},
    ]

    result = await generate_qualification_summary(
        history=history,
        lead={"name": "João Silva", "stage": "atacado", "company": "Cafeteria XYZ"},
        client=mock_client,
        model="gemini-2.5-flash",
        motivo="lead com intenção de compra — atacado",
        handoff_at="11/06/2026 14:30",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    user_msg = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "intenção de compra" in user_msg["content"]
    assert "11/06/2026 14:30" in user_msg["content"]


@pytest.mark.asyncio
async def test_llm_empty_choices_returns_fallback_with_new_header():
    """Resposta vazia do LLM deve retornar fallback com o novo cabeçalho."""
    from app.agent.summary import generate_qualification_summary

    mock_response = MagicMock()
    mock_response.choices = []
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    history = [{"role": "user", "content": "preciso de café"}]

    result = await generate_qualification_summary(
        history=history,
        lead={"name": "Maria", "stage": "atacado"},
        client=mock_client,
        model="gemini-2.5-flash",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result


@pytest.mark.asyncio
async def test_llm_exception_returns_fallback_with_new_header(caplog):
    """Exceção no LLM deve retornar fallback com o novo cabeçalho."""
    import logging
    from app.agent.summary import generate_qualification_summary

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

    history = [{"role": "user", "content": "quero café"}]

    with caplog.at_level(logging.ERROR, logger="app.agent.summary"):
        result = await generate_qualification_summary(
            history=history,
            lead={"name": "Carlos", "stage": "private_label"},
            client=mock_client,
            model="gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert any("falha na chamada LLM" in r.message for r in caplog.records)
