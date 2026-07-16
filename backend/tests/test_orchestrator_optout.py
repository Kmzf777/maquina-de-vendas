from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from tests.gemini_fakes import fake_tool_call


@pytest.mark.asyncio
async def test_registrar_optout_retorna_despedida():
    """run_agent deve retornar o texto de despedida quando registrar_optout é chamado."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-optout",
        "stage": "secretaria",
        "leads": {"id": "lead-optout", "name": "Ana", "phone": "5511900000099"},
    }

    farewell = "Entendido, sem problema. Nao entrarei mais em contato."
    # O sanitizador agora normaliza ortografia inequívoca ("Nao"→"Não") — auditoria
    # 08/07 (ortografia oscilante). O texto ENTREGUE é a versão acentuada.
    farewell_entregue = "Entendido, sem problema. Não entrarei mais em contato."

    first_response = fake_tool_call(
        "registrar_optout", {"motivo": "clicou parar mensagens"}, text=farewell
    )

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=first_response)) as m_gen, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado.") as mock_exec:

        result = await run_agent(conversation, "para de me mandar mensagem")

    assert result == farewell_entregue
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert call_args.args[0] == "registrar_optout"
    assert call_args.args[1] == {"motivo": "clicou parar mensagens"}
    # Only one LLM call — no second call after opt-out
    assert m_gen.await_count == 1


@pytest.mark.asyncio
async def test_registrar_optout_nao_envia_handoff():
    """run_agent não deve chamar send_text (mensagem de handoff) quando registrar_optout é usado."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-optout-2",
        "stage": "atacado",
        "leads": {"id": "lead-optout-2", "name": "Bruno", "phone": "5511900000088"},
    }

    first_response = fake_tool_call(
        "registrar_optout", {"motivo": "nao quer mais contato"}, text="Tudo bem, abraco!"
    )

    mock_provider = MagicMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout-2", "phone": "5511900000088", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=first_response)), \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado."):

        await run_agent(conversation, "nao quero mais")

    mock_provider.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_registrar_optout_retorna_fallback_se_sem_despedida():
    """Se o modelo não gerou texto de despedida, run_agent retorna mensagem de fallback padrão."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-optout-3",
        "stage": "secretaria",
        "leads": {"id": "lead-optout-3", "name": "Carlos", "phone": "5511900000077"},
    }

    # model didn't write farewell text (tool call only, sem texto)
    first_response = fake_tool_call("registrar_optout", {"motivo": "clicou parar mensagens"})

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout-3", "phone": "5511900000077", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=first_response)) as m_gen, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado."):

        result = await run_agent(conversation, "sair")

    # Fallback humanizado (regra 22: minúscula, sem ponto final) — auditoria 2026-06-22.
    assert result == "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
    assert m_gen.await_count == 1
