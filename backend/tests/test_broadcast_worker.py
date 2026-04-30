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
