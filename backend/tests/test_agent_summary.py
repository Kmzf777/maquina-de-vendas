# backend/tests/test_agent_summary.py
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text


def _user_text(m: AsyncMock) -> str:
    """Texto do turno de usuário enviado ao núcleo nativo (contents[0])."""
    contents = m.await_args.kwargs["contents"]
    return contents[0].parts[0].text


@pytest.mark.asyncio
async def test_empty_history_returns_new_header():
    """Histórico vazio deve retornar mensagem com o novo cabeçalho, sem chamar LLM."""
    from app.agent.summary import generate_qualification_summary

    with patch("app.agent.summary.generate", new=AsyncMock()) as m_gen:
        result = await generate_qualification_summary(
            history=[],
            lead={"name": "Ana", "stage": "atacado"},
            model="gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    m_gen.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_history_llm_receives_motivo_and_handoff_at():
    """Com histórico, motivo e handoff_at devem aparecer no contexto enviado ao LLM."""
    from app.agent.summary import generate_qualification_summary

    summary_md = (
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

    history = [
        {"role": "user", "content": "quero café para minha cafeteria"},
        {"role": "assistant", "content": "vou apresentar nossos produtos"},
    ]

    with patch("app.agent.summary.generate", new=AsyncMock(side_effect=[fake_text(summary_md)])) as m_gen:
        result = await generate_qualification_summary(
            history=history,
            lead={"name": "João Silva", "stage": "atacado", "company": "Cafeteria XYZ"},
            model="gemini-2.5-flash",
            motivo="lead com intenção de compra — atacado",
            handoff_at="11/06/2026 14:30",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert m_gen.await_count == 1
    user_msg = _user_text(m_gen)
    assert "intenção de compra" in user_msg
    assert "11/06/2026 14:30" in user_msg


@pytest.mark.asyncio
async def test_llm_empty_text_returns_fallback_with_new_header():
    """Resposta vazia do LLM (text=None) deve retornar fallback com o novo cabeçalho."""
    from app.agent.summary import generate_qualification_summary

    history = [{"role": "user", "content": "preciso de café"}]

    with patch("app.agent.summary.generate", new=AsyncMock(side_effect=[fake_text(None)])):
        result = await generate_qualification_summary(
            history=history,
            lead={"name": "Maria", "stage": "atacado"},
            model="gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result


@pytest.mark.asyncio
async def test_llm_exception_returns_fallback_with_new_header(caplog):
    """Exceção no LLM deve retornar fallback com o novo cabeçalho."""
    import logging
    from app.agent.summary import generate_qualification_summary

    history = [{"role": "user", "content": "quero café"}]

    with patch("app.agent.summary.generate", new=AsyncMock(side_effect=RuntimeError("timeout"))), \
         caplog.at_level(logging.ERROR, logger="app.agent.summary"):
        result = await generate_qualification_summary(
            history=history,
            lead={"name": "Carlos", "stage": "private_label"},
            model="gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert any("falha na chamada LLM" in r.message for r in caplog.records)
