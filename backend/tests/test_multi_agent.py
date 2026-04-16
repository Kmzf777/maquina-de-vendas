# backend/tests/test_multi_agent.py
from app.agent.prompts import get_stage_prompts, PROMPT_REGISTRY


def test_registry_has_both_agents():
    assert "valeria_inbound" in PROMPT_REGISTRY
    assert "valeria_outbound" in PROMPT_REGISTRY


def test_inbound_has_all_stages():
    prompts = get_stage_prompts("valeria_inbound")
    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        assert stage in prompts
        assert len(prompts[stage]) > 100, f"Stage {stage} prompt is too short"


def test_outbound_has_all_stages():
    prompts = get_stage_prompts("valeria_outbound")
    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        assert stage in prompts
        assert len(prompts[stage]) > 100, f"Stage {stage} outbound prompt is too short"


def test_fallback_to_inbound_on_unknown_key():
    prompts = get_stage_prompts("unknown_key")
    assert prompts is PROMPT_REGISTRY["valeria_inbound"]


def test_inbound_and_outbound_secretaria_differ():
    inbound = get_stage_prompts("valeria_inbound")
    outbound = get_stage_prompts("valeria_outbound")
    assert inbound["secretaria"] != outbound["secretaria"]


def test_orchestrator_uses_inbound_prompts_by_default():
    """Sem agent_profile_id, o orchestrator usa valeria_inbound."""
    from app.agent.orchestrator import _resolve_prompt_key
    result = _resolve_prompt_key(None)
    assert result == "valeria_inbound"


def test_orchestrator_uses_outbound_prompts_when_profile_has_outbound_key():
    from app.agent.orchestrator import _resolve_prompt_key
    profile = {"prompt_key": "valeria_outbound", "model": "gemini-3-flash-preview"}
    result = _resolve_prompt_key(profile)
    assert result == "valeria_outbound"


def test_orchestrator_falls_back_to_inbound_on_missing_prompt_key():
    from app.agent.orchestrator import _resolve_prompt_key
    profile = {"model": "gemini-3-flash-preview"}  # sem prompt_key
    result = _resolve_prompt_key(profile)
    assert result == "valeria_inbound"


def test_activate_conversation_does_not_reset_stage():
    """activate_conversation nao deve resetar o stage existente da conversa."""
    from app.conversations.service import activate_conversation
    from unittest.mock import patch, MagicMock

    mock_result = MagicMock()
    mock_result.data = [{"id": "conv-1", "stage": "atacado", "status": "active"}]

    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_result

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        activate_conversation("conv-1")

    update_call = mock_sb.table.return_value.update.call_args[0][0]
    assert "stage" not in update_call, "activate_conversation nao deve alterar o stage"
    assert update_call["status"] == "active"
