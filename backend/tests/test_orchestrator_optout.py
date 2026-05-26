import json
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


def _make_tool_call(name: str, args: dict, call_id: str = "tc-001"):
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    tc.id = call_id
    return tc


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

    tool_call = _make_tool_call("registrar_optout", {"motivo": "clicou parar mensagens"})

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = farewell
    first_msg.model_dump.return_value = {"role": "assistant", "content": farewell, "tool_calls": []}

    first_response = MagicMock()
    first_response.choices = [MagicMock(message=first_msg)]
    first_response.usage = None

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator._get_client") as mock_client, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado.") as mock_exec:

        mock_client.return_value.chat.completions.create = AsyncMock(return_value=first_response)
        result = await run_agent(conversation, "para de me mandar mensagem")

    assert result == farewell
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    assert call_args.args[0] == "registrar_optout"
    assert call_args.args[1] == {"motivo": "clicou parar mensagens"}
    # Only one LLM call — no second call after opt-out
    assert mock_client.return_value.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_registrar_optout_nao_envia_handoff():
    """run_agent não deve chamar send_text (mensagem de handoff) quando registrar_optout é usado."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-optout-2",
        "stage": "atacado",
        "leads": {"id": "lead-optout-2", "name": "Bruno", "phone": "5511900000088"},
    }

    tool_call = _make_tool_call("registrar_optout", {"motivo": "nao quer mais contato"})

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = "Tudo bem, abraco!"
    first_msg.model_dump.return_value = {"role": "assistant", "content": "Tudo bem, abraco!", "tool_calls": []}

    first_response = MagicMock()
    first_response.choices = [MagicMock(message=first_msg)]
    first_response.usage = None

    mock_provider = MagicMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout-2", "phone": "5511900000088", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator._get_client") as mock_client, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado."):

        mock_client.return_value.chat.completions.create = AsyncMock(return_value=first_response)
        await run_agent(conversation, "nao quero mais")

    mock_provider.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_registrar_optout_retorna_vazio_se_sem_despedida():
    """Se o modelo não gerou texto de despedida, run_agent retorna string vazia (não quebra)."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-optout-3",
        "stage": "secretaria",
        "leads": {"id": "lead-optout-3", "name": "Carlos", "phone": "5511900000077"},
    }

    tool_call = _make_tool_call("registrar_optout", {"motivo": "clicou parar mensagens"})

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = None  # model didn't write farewell text
    first_msg.model_dump.return_value = {"role": "assistant", "content": None, "tool_calls": []}

    first_response = MagicMock()
    first_response.choices = [MagicMock(message=first_msg)]
    first_response.usage = None

    with patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-optout-3", "phone": "5511900000077", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator._get_client") as mock_client, \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="Opt-out registrado."):

        mock_client.return_value.chat.completions.create = AsyncMock(return_value=first_response)
        result = await run_agent(conversation, "sair")

    assert result == ""
    assert mock_client.return_value.chat.completions.create.call_count == 1
