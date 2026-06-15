"""
Tests for Tasks 1.2 + 1.3: reply-context and reaction enrichment in the orchestrator.

Strategy: test the pure helpers directly (_truncate, _build_reply_marker,
_render_history_content) to avoid spinning up the full run_agent machinery
(which requires LLM mocks, DB mocks, etc.).  One integration-style test verifies
that the history-building loop in run_agent emits the marker in the messages list.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

def test_truncate_short_string_unchanged():
    from app.agent.orchestrator import _truncate
    assert _truncate("oi") == "oi"


def test_truncate_exactly_limit_unchanged():
    from app.agent.orchestrator import _truncate, _TRUNCATE_LEN
    text = "x" * _TRUNCATE_LEN
    assert _truncate(text) == text


def test_truncate_over_limit_appends_ellipsis():
    from app.agent.orchestrator import _truncate, _TRUNCATE_LEN
    text = "a" * (_TRUNCATE_LEN + 10)
    result = _truncate(text)
    assert result.endswith("…")
    assert len(result) == _TRUNCATE_LEN + 1  # 120 chars + ellipsis char


def test_truncate_custom_length():
    from app.agent.orchestrator import _truncate
    result = _truncate("hello world", length=5)
    assert result == "hello…"


# ---------------------------------------------------------------------------
# _build_reply_marker — via patched resolve_message_text_by_wamid
# ---------------------------------------------------------------------------

def test_build_reply_marker_resolved():
    from app.agent.orchestrator import _build_reply_marker
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value="Olá, tudo bem?"):
        marker = _build_reply_marker("wamid-abc")
    assert marker == '[Em resposta a: "Olá, tudo bem?"]'


def test_build_reply_marker_unresolved_soft_marker():
    from app.agent.orchestrator import _build_reply_marker
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value=None):
        marker = _build_reply_marker("wamid-abc")
    assert marker == "[Em resposta a uma mensagem anterior]"


def test_build_reply_marker_truncates_long_original():
    from app.agent.orchestrator import _build_reply_marker, _TRUNCATE_LEN
    long_text = "X" * 200
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value=long_text):
        marker = _build_reply_marker("wamid-abc")
    # marker should contain the truncated text followed by ellipsis
    assert "…" in marker
    # The quoted portion should be no longer than _TRUNCATE_LEN + len('…')
    # Extract the quoted part between the inner quotes
    inner = marker[len('[Em resposta a: "'):-2]  # strip prefix and '"]'
    assert len(inner) <= _TRUNCATE_LEN + 1  # +1 for ellipsis char


# ---------------------------------------------------------------------------
# _render_history_content — plain message (no enrichment)
# ---------------------------------------------------------------------------

def test_render_plain_message_passes_through():
    from app.agent.orchestrator import _render_history_content
    msg = {"role": "user", "content": "quero informações", "message_type": "text",
           "quoted_wamid": None, "metadata": None}
    assert _render_history_content(msg) == "quero informações"


def test_render_message_no_content_returns_empty():
    from app.agent.orchestrator import _render_history_content
    msg = {"role": "user", "content": None, "message_type": "text",
           "quoted_wamid": None, "metadata": None}
    assert _render_history_content(msg) == ""


# ---------------------------------------------------------------------------
# _render_history_content — reply enrichment (quoted_wamid)
# ---------------------------------------------------------------------------

def test_render_reply_resolved_prefixes_marker():
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "Sim, gostei muito!",
        "message_type": "text",
        "quoted_wamid": "wamid-orig-001",
        "metadata": None,
    }
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value="Você gostou do produto?"):
        result = _render_history_content(msg)

    assert result.startswith('[Em resposta a: "Você gostou do produto?"]')
    assert "Sim, gostei muito!" in result
    assert result == '[Em resposta a: "Você gostou do produto?"]\nSim, gostei muito!'


def test_render_reply_unresolved_uses_soft_marker():
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "Exatamente isso!",
        "message_type": "text",
        "quoted_wamid": "wamid-missing",
        "metadata": None,
    }
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value=None):
        result = _render_history_content(msg)

    assert result == "[Em resposta a uma mensagem anterior]\nExatamente isso!"


# ---------------------------------------------------------------------------
# _render_history_content — reaction translation
# ---------------------------------------------------------------------------

def test_render_reaction_resolved_target():
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "[reaction: meta_b64=abc==]",  # raw garbage before enrichment
        "message_type": "reaction",
        "quoted_wamid": None,
        "metadata": {"emoji": "👍", "target_wamid": "wamid-target-001"},
    }
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value="Preço ótimo, vale a pena!"):
        result = _render_history_content(msg)

    assert result == '[O lead reagiu com 👍 à mensagem: "Preço ótimo, vale a pena!"]'


def test_render_reaction_unresolved_target():
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "[reaction: meta_b64=abc==]",
        "message_type": "reaction",
        "quoted_wamid": None,
        "metadata": {"emoji": "❤️", "target_wamid": "wamid-gone"},
    }
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value=None):
        result = _render_history_content(msg)

    assert result == "[O lead reagiu com ❤️ a uma mensagem anterior]"


def test_render_reaction_no_metadata_falls_back():
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "[reaction]",
        "message_type": "reaction",
        "quoted_wamid": None,
        "metadata": None,
    }
    result = _render_history_content(msg)
    assert result == "[O lead reagiu com ? a uma mensagem anterior]"


def test_render_reaction_metadata_string_falls_back():
    """metadata coming in as a non-dict string (unexpected) should not crash."""
    from app.agent.orchestrator import _render_history_content
    msg = {
        "role": "user",
        "content": "[reaction]",
        "message_type": "reaction",
        "quoted_wamid": None,
        "metadata": "raw_string_unexpectedly",
    }
    result = _render_history_content(msg)
    # metadata is not a dict → emoji fallback "?", no target_wamid
    assert result == "[O lead reagiu com ? a uma mensagem anterior]"


def test_render_reaction_truncates_long_target():
    from app.agent.orchestrator import _render_history_content, _TRUNCATE_LEN
    long_text = "B" * 200
    msg = {
        "role": "user",
        "content": "[reaction]",
        "message_type": "reaction",
        "quoted_wamid": None,
        "metadata": {"emoji": "🔥", "target_wamid": "wamid-x"},
    }
    with patch("app.agent.orchestrator.resolve_message_text_by_wamid", return_value=long_text):
        result = _render_history_content(msg)

    assert "🔥" in result
    assert "…" in result


# ---------------------------------------------------------------------------
# Integration: history-building loop emits reply marker in messages list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_history_reply_marker_in_messages():
    """run_agent deve incluir o marcador de reply nos messages enviados ao LLM."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-reply-001",
        "stage": "secretaria",
        "leads": {"id": "lead-001", "name": "Ana", "phone": "5511999990000", "ai_enabled": True},
    }

    # History: one prior user message WITH quoted_wamid, already in DB
    fake_history = [
        {
            "role": "user",
            "content": "Sim, quero saber mais!",
            "stage": "secretaria",
            "created_at": "2026-01-01T10:00:00Z",
            "wamid": "wamid-b",
            "quoted_wamid": "wamid-a",
            "message_type": "text",
            "metadata": None,
        },
        # The current user message — same content as user_text → will be stripped
        {
            "role": "user",
            "content": "Me manda o catálogo",
            "stage": "secretaria",
            "created_at": "2026-01-01T10:01:00Z",
            "wamid": "wamid-c",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        },
    ]

    captured_messages: list = []

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(tool_calls=None, content="claro!"))]
    mock_response.usage = None

    async def fake_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return mock_response

    with patch("app.agent.orchestrator.get_history", return_value=fake_history), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-001", "phone": "5511999990000", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.resolve_message_text_by_wamid",
               return_value="Você conhece nossos produtos?"), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        await run_agent(conversation, "Me manda o catálogo")

    # Find the history user message (the one with "Sim, quero saber mais!")
    user_msgs = [m for m in captured_messages if m.get("role") == "user"]
    # First user message in the list should have the reply marker
    assert any(
        '[Em resposta a: "Você conhece nossos produtos?"]' in m["content"]
        for m in user_msgs
    ), f"Marker not found in user messages: {user_msgs}"


# ---------------------------------------------------------------------------
# Integration: current message with quoted_wamid gets reply marker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_current_message_reply_marker():
    """Se a mensagem atual tem quoted_wamid, user_text deve carregar o marcador."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-reply-002",
        "stage": "secretaria",
        "leads": {"id": "lead-002", "name": "Pedro", "phone": "5511888880000", "ai_enabled": True},
    }

    user_text = "Sim, me interessa!"

    # History: the current message is the last entry, WITH quoted_wamid
    fake_history = [
        {
            "role": "user",
            "content": user_text,
            "stage": "secretaria",
            "created_at": "2026-01-01T11:00:00Z",
            "wamid": "wamid-curr",
            "quoted_wamid": "wamid-prev",
            "message_type": "text",
            "metadata": None,
        },
    ]

    captured_messages: list = []

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(tool_calls=None, content="ótimo!"))]
    mock_response.usage = None

    async def fake_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return mock_response

    with patch("app.agent.orchestrator.get_history", return_value=fake_history), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-002", "phone": "5511888880000", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.resolve_message_text_by_wamid",
               return_value="Quer saber sobre nosso plano premium?"), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        await run_agent(conversation, user_text)

    # The last user message in the captured list should be the enriched current message
    user_msgs = [m for m in captured_messages if m.get("role") == "user"]
    last_user = user_msgs[-1]
    assert '[Em resposta a: "Quer saber sobre nosso plano premium?"]' in last_user["content"]
    assert user_text in last_user["content"]
