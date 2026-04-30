"""Tests for broadcast worker ai_enabled logic.

These tests verify the invariant: disparo com agente → ai_enabled=True,
disparo sem agente → ai_enabled=False.
"""


def _build_conv_updates(broadcast: dict) -> dict:
    """Replica a lógica de conv_updates do worker para teste isolado.

    Copiar EXATAMENTE a mesma lógica do worker.py — se o worker mudar, mudar aqui.
    """
    conv_updates: dict = {"status": "template_sent"}
    if broadcast.get("agent_profile_id"):
        conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
        conv_updates["ai_enabled"] = True
    else:
        conv_updates["ai_enabled"] = False
    return conv_updates


def test_without_agent_disables_ai():
    """Disparo sem agente deve forçar ai_enabled=False na conversa."""
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": None,
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is False
    assert "agent_profile_id" not in updates


def test_without_agent_empty_string_disables_ai():
    """agent_profile_id vazio deve ser tratado como ausente."""
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": "",
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is False


def test_with_agent_enables_ai():
    """Disparo com agente deve forçar ai_enabled=True e setar agent_profile_id."""
    agent_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": agent_id,
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is True
    assert updates["agent_profile_id"] == agent_id


def test_status_always_template_sent():
    """conv_updates deve sempre incluir status=template_sent."""
    for agent_id in [None, "some-uuid"]:
        broadcast = {"agent_profile_id": agent_id}
        updates = _build_conv_updates(broadcast)
        assert updates["status"] == "template_sent"
