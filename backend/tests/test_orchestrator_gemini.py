from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_is_gemini_model_verdadeiro_para_prefixo_gemini():
    from app.agent.orchestrator import _is_gemini_model
    assert _is_gemini_model("gemini-2.5-flash") is True
    assert _is_gemini_model("gemini-1.5-pro") is True
    assert _is_gemini_model("gpt-4.1-mini") is False
    assert _is_gemini_model("o4-mini") is False


def test_get_client_roteia_gemini_para_cliente_gemini():
    from app.agent.orchestrator import _get_client
    with patch("app.agent.orchestrator._get_gemini") as mock_gemini:
        result = _get_client("gemini-2.5-flash")
        mock_gemini.assert_called_once()
        assert result is mock_gemini.return_value


def test_get_client_roteia_qualquer_modelo_para_gemini():
    from app.agent.orchestrator import _get_client
    with patch("app.agent.orchestrator._get_gemini") as mock_gemini:
        for model in ("gpt-4.1-mini", "modelo-desconhecido", "gemini-2.5-flash"):
            result = _get_client(model)
            assert result is mock_gemini.return_value


@pytest.mark.asyncio
async def test_run_agent_usa_cliente_gemini_quando_profile_usa_gemini():
    conversation = {
        "id": "conv-gemini-1",
        "lead_id": "lead-1",
        "stage": "secretaria",
        "leads": {"id": "lead-1", "phone": "5511999990000"},
    }
    mock_response = MagicMock()
    mock_response.usage = None
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Olá!"
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-1", "phone": "5511999990000"}), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={
             "model": "gemini-2.5-flash",
             "prompt_key": "valeria_inbound",
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_tools_for_stage", return_value=[]), \
         patch("app.agent.orchestrator.build_system_prompt", return_value="system"), \
         patch("app.agent.orchestrator._get_client", return_value=mock_client) as mock_get_client:
        from app.agent.orchestrator import run_agent
        result = await run_agent(conversation, "oi", agent_profile_id="profile-1")

    mock_get_client.assert_called_with("gemini-2.5-flash")
    assert result == "Olá!"


@pytest.mark.asyncio
async def test_run_agent_coage_modelo_nao_gemini_para_gemini_flash():
    conversation = {
        "id": "conv-gemini-2",
        "lead_id": "lead-1",
        "stage": "secretaria",
        "leads": {"id": "lead-1", "phone": "5511999990000"},
    }
    mock_response = MagicMock()
    mock_response.usage = None
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Olá!"
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-1", "phone": "5511999990000"}), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={
             "model": "gpt-4.1",
             "prompt_key": "valeria_inbound",
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_tools_for_stage", return_value=[]), \
         patch("app.agent.orchestrator.build_system_prompt", return_value="system"), \
         patch("app.agent.orchestrator._get_client", return_value=mock_client) as mock_get_client:
        from app.agent.orchestrator import run_agent
        result = await run_agent(conversation, "oi", agent_profile_id="profile-1")

    mock_get_client.assert_called_with("gemini-2.5-flash")
    assert result == "Olá!"
