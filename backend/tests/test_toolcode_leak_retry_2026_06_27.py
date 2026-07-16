"""Vazamento de tool_code no retry (lead 5567996264477): a rede deve cobrir o retry e o optout.

Falha real: 1a resposta = tool_code puro -> strip -> vazio -> retry reincidiu no tool_code ->
retornado cru (o caminho de retry nao sanitizava) -> vazou. Apos a centralizacao, o codigo cru
NUNCA chega ao cliente. A partir de 2026-06-30 (Change C), o turno generico vazio NAO aborta
mais em silencio: devolve o fallback generico honesto (_SAFETY_FALLBACK_GENERIC) em vez de "".
O invariante critico permanece: o texto entregue jamais contem 'tool_code' nem 'default_api'.

Contrato Gemini nativo (migração 09/07/2026): as chamadas ao LLM saem por
`app.agent.orchestrator.generate` (gemini_client) — fakes de tests/gemini_fakes.py.
O vazamento continua possível: o modelo serializa o function-call como CÓDIGO no texto
(function_calls vazio), e a rede anti-tool_code segue sendo a defesa determinística.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call

_LEAK = "<tool_code> print(default_api.salvar_nome(nome='João Paulo Nogueira Alves')) </tool_code>"


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
    # Etapa 2: inicial + retry1 vazando tool_code (ambos sanitizados para "") ainda disparam
    # o retry2 (temperatura elevada) — também vaza aqui, para o teste chegar ao fallback.
    m_gen = AsyncMock(side_effect=[
        fake_text(_LEAK), fake_text(_LEAK), fake_text(_LEAK),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation(), "Sim\nJOÃO PAULO NOGUEIRA ALVES")

    assert result == _SAFETY_FALLBACK_GENERIC, (
        "turno genérico vazio deve cair no fallback honesto, não em silêncio (Change C)"
    )
    assert "tool_code" not in result
    assert "default_api" not in result
    assert m_gen.await_count == 3, "deve ter feito o retry e o retry2 (Etapa 2)"


@pytest.mark.asyncio
async def test_toolcode_leak_inicial_retry_limpo_recupera_texto():
    """Inicial vaza tool_code → strip vazio → retry traz texto humano limpo → usa o texto."""
    from app.agent.orchestrator import run_agent
    m_gen = AsyncMock(side_effect=[
        fake_text(_LEAK),
        fake_text("boa Paulo, prazer\n\nsua demanda é pro mercado brasileiro ou exportação?"),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=_history()), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation(), "Sim\nJOÃO PAULO NOGUEIRA ALVES")

    assert result == "boa Paulo, prazer\n\nsua demanda é pro mercado brasileiro ou exportação?"
    assert "tool_code" not in result


@pytest.mark.asyncio
async def test_optout_com_tool_code_cai_no_fallback_estatico():
    """Se a despedida do optout vier como tool_code puro, o strip esvazia → fallback estático."""
    from app.agent.orchestrator import run_agent

    # registrar_optout com a despedida vazada como tool_code no texto do MESMO turno
    m_gen = AsyncMock(return_value=fake_tool_call(
        "registrar_optout", {"motivo": "clicou parar"}, text=_LEAK,
    ))

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-jp", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen), \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="ok"):
        result = await run_agent(_conversation(), "para de me mandar mensagem")

    assert "tool_code" not in result
    assert "default_api" not in result
    assert result == "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
