from unittest.mock import MagicMock, patch

import pytest

from scripts.rehearsal import gemini_actor


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_next_lead_message_returns_stripped_text(mock_get_model):
    model = MagicMock()
    response = MagicMock()
    response.text = "  qual o preco?  \n"
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.generate_next_lead_message(
        persona_prompt="voce e um lead",
        conversation_history=[
            {"role": "assistant", "content": "oi, em que posso ajudar?"},
        ],
        last_assistant_message="oi, em que posso ajudar?",
    )

    assert result == "qual o preco?"
    model.generate_content.assert_called_once()


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_retries_on_exception(mock_get_model):
    model = MagicMock()
    response_ok = MagicMock(text="ok")
    model.generate_content.side_effect = [Exception("rate limit"), Exception("500"), response_ok]
    mock_get_model.return_value = model

    result = gemini_actor.generate_next_lead_message("persona", [], "")

    assert result == "ok"
    assert model.generate_content.call_count == 3


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_gives_up_after_max_retries(mock_get_model):
    model = MagicMock()
    model.generate_content.side_effect = Exception("persistent error")
    mock_get_model.return_value = model

    with pytest.raises(gemini_actor.GeminiFailure):
        gemini_actor.generate_next_lead_message("persona", [], "")


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_judge_conversation_parses_json(mock_get_model):
    model = MagicMock()
    response = MagicMock()
    response.text = '''```json
{
  "bot_score_1_10": 8,
  "linhas_robotizadas": ["soou strange"],
  "resposta_incorreta_ou_inventada": null,
  "veredito_curto": "chegou ao objetivo"
}
```'''
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.judge_conversation(
        transcript="conversa completa aqui",
        archetype_id="A1",
        criteria_description="critérios do A1",
    )

    assert result["bot_score_1_10"] == 8
    assert result["veredito_curto"] == "chegou ao objetivo"


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_judge_falls_back_on_invalid_json(mock_get_model):
    model = MagicMock()
    response = MagicMock(text="isto nao eh json")
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.judge_conversation("x", "A1", "y")

    assert "error" in result
    assert result.get("bot_score_1_10") is None
