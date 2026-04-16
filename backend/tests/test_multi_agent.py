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


def test_broadcast_worker_assigns_agent_profile_to_conversation():
    """Após enviar template, worker grava agent_profile_id na conversa."""
    import asyncio
    import app.broadcast.worker as worker_module
    from unittest.mock import AsyncMock, MagicMock, patch

    broadcast = {
        "id": "bc-1",
        "status": "running",
        "template_name": "teste",
        "template_variables": {},
        "channel_id": "ch-1",
        "agent_profile_id": "ap-outbound",
        "send_interval_min": 0,
        "send_interval_max": 0,
    }
    lead = {"id": "lead-1", "phone": "5511999990000"}
    broadcast_lead = {"id": "bl-1", "leads": lead}

    mock_conv = {"id": "conv-1", "stage": "atacado"}
    mock_get_conv = MagicMock(return_value=mock_conv)
    mock_update_conv = MagicMock()
    mock_provider = MagicMock()
    mock_provider.send_template = AsyncMock()

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    with patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[broadcast_lead]), \
         patch("app.broadcast.worker.mark_broadcast_lead_sent"), \
         patch("app.broadcast.worker.increment_broadcast_sent"), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-1"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.get_or_create_conversation", mock_get_conv), \
         patch("app.broadcast.worker.update_conversation", mock_update_conv), \
         patch("app.broadcast.worker.get_supabase", return_value=mock_sb):

        asyncio.run(worker_module.process_single_broadcast(broadcast))

    mock_update_conv.assert_called_once_with(
        "conv-1",
        agent_profile_id="ap-outbound",
        status="template_sent",
    )


def test_processor_resolves_agent_profile_from_conversation():
    """Processor usa agent_profile_id da conversa (prioridade sobre canal)."""
    conv_agent = "ap-outbound"
    channel_agent = "ap-inbound"

    conversation = {
        "id": "conv-1",
        "stage": "atacado",
        "status": "active",
        "agent_profile_id": conv_agent,
    }
    channel = {
        "id": "ch-1",
        "agent_profiles": {"id": channel_agent, "name": "Inbound"},
    }

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result == conv_agent


def test_processor_falls_back_to_channel_agent():
    """Sem agent_profile_id na conversa, usa o agente do canal."""
    channel_agent = "ap-inbound"
    conversation = {"id": "conv-1", "stage": "secretaria", "status": "active"}
    channel = {
        "id": "ch-1",
        "agent_profiles": {"id": channel_agent, "name": "Inbound"},
    }

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result == channel_agent


def test_processor_returns_none_when_no_agent():
    """Sem agente em conversa nem canal, retorna None (human-only mode)."""
    conversation = {"id": "conv-1", "stage": "secretaria", "status": "active"}
    channel = {"id": "ch-1"}

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result is None
