"""Tests for the three UX fixes from Iasmin Silver investigation (lead 5551996918183).

Fix A — max_tokens raised from 500 to 1024 so long responses are never truncated.
Fix B — enviar_fotos/enviar_foto_produto defer media to processor so text arrives first.
Fix C — frustration guardrail in processor bypasses LLM on clear desistência/human-request signals.
"""

import logging
import re
import unicodedata
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fix A: max_tokens is 1024 in all orchestrator calls
# ---------------------------------------------------------------------------

def test_orchestrator_all_calls_use_1024_tokens():
    """All LLM calls in orchestrator must use max_tokens=1024, never 500."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).parents[1] / "app" / "agent" / "orchestrator.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "max_tokens" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value == 1024, (
                        f"Encontrado max_tokens={kw.value.value} na linha {node.lineno} "
                        "— esperado 1024"
                    )


# ---------------------------------------------------------------------------
# Fix B: deferred media — pop_deferred_media + processor dispatch
# ---------------------------------------------------------------------------

def test_pop_deferred_media_returns_and_clears():
    """pop_deferred_media returns queued items and leaves the dict clean."""
    from app.agent.tools import _deferred_media, pop_deferred_media

    _deferred_media["conv-x"] = [
        {"b64": "AAAA", "mimetype": "image/jpeg", "caption": "c1"},
        {"b64": "BBBB", "mimetype": "image/png", "caption": "c2"},
    ]

    result = pop_deferred_media("conv-x")
    assert len(result) == 2
    assert result[0]["b64"] == "AAAA"
    assert "conv-x" not in _deferred_media


def test_pop_deferred_media_empty_conv():
    """pop_deferred_media returns empty list for unknown conversation_id."""
    from app.agent.tools import pop_deferred_media
    assert pop_deferred_media("conv-nonexistent") == []


@pytest.mark.asyncio
async def test_enviar_fotos_does_not_call_provider_directly():
    """enviar_fotos must queue photos to _deferred_media, NOT call send_image_base64.

    Uses the actual app/photos directory so no Path mocking is needed.
    Only save_message is patched to avoid Supabase network calls.
    """
    from app.agent.tools import execute_tool, pop_deferred_media, _deferred_media

    conv_id = "conv-defer-b"
    _deferred_media.pop(conv_id, None)

    with patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_history", return_value=[]):
        result = await execute_tool(
            "enviar_fotos",
            {"categoria": "private_label"},
            lead_id="lead-b",
            phone="5511999990000",
            conversation_id=conv_id,
        )

    # Deferred queue must have the photos (real photos from app/photos/private_label/)
    deferred = pop_deferred_media(conv_id)
    assert len(deferred) > 0, "Esperava fotos na fila deferred"
    assert all("b64" in item and "mimetype" in item for item in deferred)

    # Confirm the tool did NOT try to call a provider
    assert "enfileirada" in result.lower() or "enviada" in result.lower()


@pytest.mark.asyncio
async def test_enviar_foto_produto_does_not_call_provider_directly():
    """enviar_foto_produto must queue photo to _deferred_media, NOT call send_image_base64."""
    from app.agent.tools import execute_tool, pop_deferred_media, _deferred_media

    conv_id = "conv-defer-c"
    _deferred_media.pop(conv_id, None)

    with patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.get_history", return_value=[]):
        result = await execute_tool(
            "enviar_foto_produto",
            {"categoria": "atacado", "produto": "classico"},
            lead_id="lead-c",
            phone="5511999990000",
            conversation_id=conv_id,
        )

    deferred = pop_deferred_media(conv_id)
    assert len(deferred) == 1, f"Esperava 1 foto na fila, got {len(deferred)}"
    assert deferred[0]["b64"] is not None
    assert "enfileirada" in result.lower() or "enviada" in result.lower()


@pytest.mark.asyncio
async def test_processor_sends_deferred_media_after_text():
    """Processor sends deferred media AFTER text bubbles — preserving WhatsApp order."""
    from app.buffer.processor import process_buffered_messages
    from app.agent.tools import _deferred_media

    lead_data = {"id": "lead-dm", "phone": "+5511999990000", "ai_enabled": True, "human_control": False}
    conv_data = {
        "id": "conv-dm",
        "lead_id": "lead-dm",
        "stage": "private_label",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }
    channel_data = {
        "id": "ch-dm",
        "mode": "ai",
        "agent_profiles": None,
        "provider_config": {"phone_number_id": "dm-ph-id"},
    }

    # Pre-load deferred media as enviar_fotos would have
    _deferred_media["conv-dm"] = [
        {"b64": "AAAA", "mimetype": "image/jpeg", "caption": "Foto 1"},
        {"b64": "BBBB", "mimetype": "image/jpeg", "caption": "Foto 2"},
    ]

    call_log = []
    mock_provider = MagicMock()
    mock_provider.send_text = AsyncMock(side_effect=lambda ph, txt: call_log.append(("text", txt)))
    mock_provider.send_image_base64 = AsyncMock(
        side_effect=lambda ph, b64, mime, **kw: call_log.append(("image", b64))
    )

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_data), \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.get_provider", return_value=mock_provider), \
         patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="Aqui estão as fotos")), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["Aqui estão as fotos"]), \
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        await process_buffered_messages("+5511999990000", "manda as fotos", channel_id="ch-dm")

    # Verify order: text THEN images
    assert len(call_log) == 3, f"Esperava 1 texto + 2 imagens, got: {call_log}"
    assert call_log[0] == ("text", "Aqui estão as fotos"), "Texto deve chegar ANTES das imagens"
    assert call_log[1][0] == "image"
    assert call_log[2][0] == "image"


# ---------------------------------------------------------------------------
# Fix C: frustration guardrail — pattern matching
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


@pytest.mark.parametrize("message,should_fire", [
    ("desisto", True),
    ("Desisto", True),
    ("desisti de entrar em contato", True),
    ("quero falar com uma pessoa", True),
    ("quero falar com humano", True),
    ("falar com atendente", True),
    ("me passa pro humano", True),
    ("atendimento pessimo", True),
    ("atendimento ruim", True),
    # should NOT fire
    ("oi, quero saber sobre private label", False),
    ("quanto custa o cafe", False),
    ("ta bom, pode falar", False),
    ("ta dificil encontrar fornecedor no mercado", False),
])
def test_frustration_patterns_match(message, should_fire):
    """_FRUSTRATION_PATTERNS correctly identifies frustration signals."""
    from app.buffer.processor import _FRUSTRATION_PATTERNS
    normalized = _normalize(message)
    matched = any(re.search(p, normalized) for p in _FRUSTRATION_PATTERNS)
    assert matched == should_fire, (
        f"Mensagem {message!r}: esperava match={should_fire}, got match={matched}"
    )


@pytest.mark.asyncio
async def test_frustration_guardrail_returns_true_and_calls_execute_tool(caplog):
    """_check_frustration_guardrail returns True and calls encaminhar_humano."""
    from app.buffer.processor import _check_frustration_guardrail

    captured = []

    async def fake_execute_tool(name, args, lead_id=None, phone=None, conversation_id=None):
        captured.append((name, args))

    with patch("app.agent.tools.execute_tool", new=fake_execute_tool), \
         caplog.at_level(logging.WARNING, logger="app.buffer.processor"):
        result = await _check_frustration_guardrail(
            "desisto",
            lead_id="lead-fg",
            phone="5511999990000",
            conversation_id="conv-fg",
        )

    assert result is True
    assert any("FRUSTRATION_GUARDRAIL" in r.message for r in caplog.records)
    assert len(captured) == 1
    assert captured[0][0] == "encaminhar_humano"


@pytest.mark.asyncio
async def test_frustration_guardrail_returns_false_for_normal_message():
    """_check_frustration_guardrail returns False and never calls execute_tool for normal messages."""
    from app.buffer.processor import _check_frustration_guardrail

    tool_calls = []

    async def fake_execute_tool(*a, **kw):
        tool_calls.append(a)

    with patch("app.agent.tools.execute_tool", new=fake_execute_tool):
        result = await _check_frustration_guardrail(
            "quanto custa o cafe 250g",
            lead_id="lead-ok",
            phone="5511999990000",
            conversation_id="conv-ok",
        )

    assert result is False
    assert not tool_calls


@pytest.mark.asyncio
async def test_processor_guardrail_skips_run_agent_on_desisto():
    """When message is 'desisto', processor fires guardrail and never calls run_agent."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {"id": "lead-des", "phone": "+5511999990000", "ai_enabled": True, "human_control": False}
    conv_data = {
        "id": "conv-des",
        "lead_id": "lead-des",
        "stage": "private_label",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }
    channel_data = {
        "id": "ch-des",
        "mode": "ai",
        "agent_profiles": None,
        "provider_config": {"phone_number_id": "des-ph-id"},
    }

    mock_run_agent = AsyncMock(return_value="texto do agente")
    mock_execute_tool = AsyncMock(return_value="Lead encaminhado")

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_data), \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.get_provider"), \
         patch("app.buffer.processor.run_agent", new=mock_run_agent), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.agent.tools.execute_tool", new=mock_execute_tool), \
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        await process_buffered_messages("+5511999990000", "desisto", channel_id="ch-des")

    # LLM must NOT have been called
    mock_run_agent.assert_not_called()
    # encaminhar_humano must have been called via guardrail
    mock_execute_tool.assert_called_once()
    assert mock_execute_tool.call_args[0][0] == "encaminhar_humano"


# ---------------------------------------------------------------------------
# Fix D: dynamic typing-speed delay between bubbles
# ---------------------------------------------------------------------------

def test_bubble_delays_rehearsal_mode_all_zero():
    """In rehearsal mode, all delays must be 0.0 regardless of content."""
    from app.buffer.processor import _bubble_delays
    bubbles = ["curta", "a" * 50, "b" * 100]
    delays = _bubble_delays(bubbles, is_rehearsal=True)
    assert delays == [0.0, 0.0, 0.0]


def test_bubble_delays_empty_list():
    """Empty bubble list returns empty delays."""
    from app.buffer.processor import _bubble_delays
    assert _bubble_delays([], is_rehearsal=False) == []


def test_typing_constants_tuned_for_humans():
    """Cadência humana lenta: 6 cps, piso 4s, teto 12s, pausa de transição 1.5s."""
    from app.buffer.processor import (
        _TYPING_CHARS_PER_SEC, _MIN_BUBBLE_DELAY, _MAX_BUBBLE_DELAY, _BUBBLE_TRANSITION_PAUSE,
    )
    assert _TYPING_CHARS_PER_SEC == 6.0
    assert _MIN_BUBBLE_DELAY == 4.0
    assert _MAX_BUBBLE_DELAY == 12.0
    assert _BUBBLE_TRANSITION_PAUSE == 1.5


def test_bubble_delays_first_bubble_now_has_typing_delay():
    """O 1º balão NÃO é mais imediato: ganha delay de digitação (sem pausa de transição)."""
    from app.buffer.processor import _bubble_delays
    delays = _bubble_delays(["a" * 48], is_rehearsal=False, llm_latency=0.0)
    assert delays[0] == pytest.approx(48 / 6.0)  # 8.0s (clamp [4,12], sem +1.5)


def test_bubble_delays_first_bubble_subtracts_llm_latency():
    """Latência da LLM conta como tempo já 'gasto' — é subtraída do delay do 1º balão."""
    from app.buffer.processor import _bubble_delays
    # 48 chars / 6 = 8.0s de digitação; LLM já levou 2s → resta 6.0s de delay
    delays = _bubble_delays(["a" * 48], is_rehearsal=False, llm_latency=2.0)
    assert delays[0] == pytest.approx(6.0)


def test_bubble_delays_first_bubble_floors_at_zero_when_llm_slow():
    """Se a LLM demorou mais que o tempo de digitação, não há espera extra (>= 0)."""
    from app.buffer.processor import _bubble_delays
    delays = _bubble_delays(["a" * 24], is_rehearsal=False, llm_latency=30.0)
    assert delays[0] == 0.0  # 24/6=4s - 30s → floor 0


def test_bubble_delays_short_bubble_clamped_to_min_plus_transition():
    """Balão curto ('Sim') → piso MIN + pausa de transição (4.0 + 1.5 = 5.5)."""
    from app.buffer.processor import _bubble_delays, _MIN_BUBBLE_DELAY, _BUBBLE_TRANSITION_PAUSE
    # "Sim" = 3 chars → 3/6 = 0.5s → clamp p/ MIN (4.0) + 1.5 transição
    delays = _bubble_delays(["Sim", "segunda mensagem"], is_rehearsal=False)
    assert delays[1] == _MIN_BUBBLE_DELAY + _BUBBLE_TRANSITION_PAUSE


def test_bubble_delays_long_bubble_clamped_to_max_plus_transition():
    """Balão muito longo (> 72 chars a 6 cps) → teto MAX + transição (12.0 + 1.5 = 13.5)."""
    from app.buffer.processor import _bubble_delays, _MAX_BUBBLE_DELAY, _BUBBLE_TRANSITION_PAUSE
    # 160 chars / 6 = 26.7s → clamp p/ MAX (12.0) + 1.5
    long_bubble = "a" * 160
    delays = _bubble_delays([long_bubble, "próxima mensagem"], is_rehearsal=False)
    assert delays[1] == _MAX_BUBBLE_DELAY + _BUBBLE_TRANSITION_PAUSE


def test_bubble_delays_medium_bubble_proportional_plus_transition():
    """Balão médio (48 chars) → proporcional + pausa de transição."""
    from app.buffer.processor import (
        _bubble_delays, _MIN_BUBBLE_DELAY, _MAX_BUBBLE_DELAY, _TYPING_CHARS_PER_SEC,
        _BUBBLE_TRANSITION_PAUSE,
    )
    medium_bubble = "a" * 48   # 48 / 6 = 8.0s
    delays = _bubble_delays([medium_bubble, "segunda"], is_rehearsal=False)
    typing = 48 / _TYPING_CHARS_PER_SEC  # 8.0
    assert _MIN_BUBBLE_DELAY <= typing <= _MAX_BUBBLE_DELAY
    assert delays[1] == typing + _BUBBLE_TRANSITION_PAUSE  # 9.5


def test_bubble_delays_delay_per_previous_bubble():
    """Delays dos balões seguintes: clamp(len(prev)/CPS) + pausa de transição."""
    from app.buffer.processor import _bubble_delays, _TYPING_CHARS_PER_SEC, _BUBBLE_TRANSITION_PAUSE
    b0 = "a" * 30  # → delay antes de b1: 30/6 = 5.0s + 1.5
    b1 = "a" * 48  # → delay antes de b2: 48/6 = 8.0s + 1.5
    b2 = "a" * 5   # curto, mas o delay é baseado em b1
    delays = _bubble_delays([b0, b1, b2], is_rehearsal=False, llm_latency=10.0)
    # llm_latency >> 30/6 → 1º balão floored em 0
    assert delays[0] == 0.0
    assert delays[1] == pytest.approx(30 / _TYPING_CHARS_PER_SEC + _BUBBLE_TRANSITION_PAUSE)  # 6.5s
    assert delays[2] == pytest.approx(48 / _TYPING_CHARS_PER_SEC + _BUBBLE_TRANSITION_PAUSE)  # 9.5s
