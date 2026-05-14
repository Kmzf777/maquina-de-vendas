"""Tests for broadcast worker ai_enabled logic."""

from app.broadcast.worker import _build_conv_updates, _broadcast_ai_enabled


def test_conv_updates_without_agent():
    """Disparo sem agente: conv_updates tem só status, sem ai_enabled."""
    broadcast = {"template_name": "ola_mundo", "agent_profile_id": None}
    updates = _build_conv_updates(broadcast)
    assert updates["status"] == "template_sent"
    assert "ai_enabled" not in updates
    assert "agent_profile_id" not in updates


def test_conv_updates_with_agent():
    """Disparo com agente: conv_updates tem status e agent_profile_id, sem ai_enabled."""
    agent_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    broadcast = {"template_name": "ola_mundo", "agent_profile_id": agent_id}
    updates = _build_conv_updates(broadcast)
    assert updates["status"] == "template_sent"
    assert updates["agent_profile_id"] == agent_id
    assert "ai_enabled" not in updates


def test_broadcast_ai_enabled_without_agent():
    """Disparo sem agente → ai_enabled=False no lead."""
    assert _broadcast_ai_enabled({"agent_profile_id": None}) is False
    assert _broadcast_ai_enabled({"agent_profile_id": ""}) is False
    assert _broadcast_ai_enabled({}) is False


def test_broadcast_ai_enabled_with_agent():
    """Disparo com agente → ai_enabled=True no lead."""
    assert _broadcast_ai_enabled({"agent_profile_id": "some-uuid"}) is True


def test_status_always_template_sent():
    """conv_updates sempre tem status=template_sent."""
    for agent_id in [None, "some-uuid"]:
        broadcast = {"agent_profile_id": agent_id}
        updates = _build_conv_updates(broadcast)
        assert updates["status"] == "template_sent"


def test_broadcast_ai_enabled_human_channel_without_agent():
    """Canal humano sem agente → False (comportamento esperado mesmo sem agent)."""
    channel = {"mode": "human"}
    assert _broadcast_ai_enabled({"agent_profile_id": None}, channel=channel) is False


def test_broadcast_ai_enabled_human_channel_with_agent():
    """Canal humano COM agente configurado → ainda False (canal humano tem precedência)."""
    channel = {"mode": "human"}
    assert _broadcast_ai_enabled({"agent_profile_id": "some-uuid"}, channel=channel) is False


def test_broadcast_ai_enabled_ai_channel_with_agent():
    """Canal IA com agente → True."""
    channel = {"mode": "ai"}
    assert _broadcast_ai_enabled({"agent_profile_id": "some-uuid"}, channel=channel) is True


def test_broadcast_ai_enabled_ai_channel_without_agent():
    """Canal IA sem agente → False."""
    channel = {"mode": "ai"}
    assert _broadcast_ai_enabled({"agent_profile_id": None}, channel=channel) is False


def test_broadcast_ai_enabled_no_channel_arg_backwards_compat():
    """Sem channel (arg omitido) → comportamento legado inalterado."""
    assert _broadcast_ai_enabled({"agent_profile_id": "uuid"}) is True
    assert _broadcast_ai_enabled({"agent_profile_id": None}) is False
