"""Correções do dossiê outbound (auditoria 2026-06-25):

C1 — `\n` LITERAL vazando nos follow-ups: o LLM devolve a barra+n crua e o cliente lê
     `\n` na tela. `_normalize_literal_newlines` converte para quebra real antes do envio.
B2 — race venda × handoff: um turno concorrente desliga a IA durante o pacing das bolhas;
     o processor revalida `ai_enabled` antes de cada bolha e aborta o resto (lead 5544991611703).
C4 — integridade de preço: `_build_catalog_block` proíbe amaciar/alterar o preço tabelado.
"""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================ C1 — newline literal ============================

def test_normalize_literal_newlines_converts_backslash_n():
    from app.follow_up.scheduler import _normalize_literal_newlines
    # entrada com a sequência LITERAL barra+n (dois caracteres)
    raw = "chegam frescos\\n\\nou se for pro seu negocio"
    out = _normalize_literal_newlines(raw)
    assert "\\n" not in out          # nenhuma barra literal sobra
    assert out == "chegam frescos\n\nou se for pro seu negocio"


def test_normalize_literal_newlines_preserves_real_newlines_and_text():
    from app.follow_up.scheduler import _normalize_literal_newlines
    assert _normalize_literal_newlines("ja com\nquebra real") == "ja com\nquebra real"
    assert _normalize_literal_newlines("sem quebra nenhuma") == "sem quebra nenhuma"
    assert _normalize_literal_newlines("") == ""
    assert _normalize_literal_newlines("misto\\r\\nfim") == "misto\nfim"


def _make_job():
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "id": "job-c1", "conversation_id": "conv-c1", "lead_id": "lead-c1", "sequence": 1,
        "leads": {"id": "lead-c1", "phone": "+5511914799202", "last_customer_message_at": now_iso},
        "channels": {"id": "ch-c1", "name": "Canal", "provider": "meta_cloud",
                     "provider_config": {"phone_number_id": "1", "access_token": "t"}, "mode": "ai"},
        "conversations": {"id": "conv-c1", "stage": "secretaria", "followup_enabled": True,
                          "last_customer_message_at": now_iso},
    }


def _sb_with_history():
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
        .order.return_value.limit.return_value.execute.return_value.data) = [
        {"role": "user", "content": "oi"},
    ]
    return sb


@pytest.mark.asyncio
async def test_followup_sends_sanitized_text_without_literal_newline():
    """O follow-up NUNCA pode enviar a barra+n crua — o cliente leria '\\n' na tela."""
    job = _make_job()
    suja = "lembrei do nosso papo\\n\\nainda faz sentido pro seu negocio"
    captured = {}

    async def _send_text(to, text):
        captured["text"] = text
        return {}

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=_sb_with_history()), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler.resolve_send_target", return_value="+5511914799202"), \
         patch("app.follow_up.scheduler.extract_wamid", return_value="w1"), \
         patch("app.follow_up.scheduler._mark_sent"), \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message",
               return_value=(suja, "stop")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(side_effect=_send_text)
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    assert "\\n" not in captured["text"]
    assert captured["text"] == "lembrei do nosso papo\n\nainda faz sentido pro seu negocio"


def test_followup_prompt_no_longer_primes_literal_newline():
    """A instrução de follow-up não pode mais conter o literal barra+n (que escora o bug)."""
    from app.follow_up.scheduler import _FOLLOWUP_REENGAGE_INSTRUCTION as instr
    assert "\\n\\n" not in instr
    assert "linha em branco" in instr


# ============================ C4 — preço verbatim ============================

def test_catalog_block_pins_prices_and_forbids_softening():
    from app.agent.orchestrator import _build_catalog_block
    block = _build_catalog_block("- **Café X**\n  - Preço: R$ 25,70")
    assert "ESTRITAMENTE PROIBIDA" in block
    # proíbe os amaciadores que apareceram na auditoria
    for hedge in ("por volta de", "em torno de", "aproximadamente"):
        assert hedge in block
    # manda confirmar a variação antes de cotar (caso 25,70 vs 26,70)
    assert "variação" in block or "variacao" in block
    # o catálogo injetado continua presente
    assert "R$ 25,70" in block


# ============================ B2 — race venda × handoff ======================

def test_ai_still_enabled_reads_fresh_flag():
    from app.buffer import processor
    with patch.object(processor, "get_lead", return_value={"ai_enabled": True}):
        assert processor._ai_still_enabled("lead-x") is True
    with patch.object(processor, "get_lead", return_value={"ai_enabled": False}):
        assert processor._ai_still_enabled("lead-x") is False
    # fail-open: erro de leitura → assume habilitado (não engole a mensagem)
    with patch.object(processor, "get_lead", side_effect=RuntimeError("db down")):
        assert processor._ai_still_enabled("lead-x") is True


def _make_lead():
    return {"id": "lead-b2", "phone": "+5544991611703", "stage": "atacado",
            "status": "active", "ai_enabled": True, "name": "Arthur"}


def _make_channel():
    return {"id": "ch-b2", "is_active": True, "mode": "ai",
            "agent_profiles": {"id": "p1", "stages": {}},
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _make_conversation():
    return {"id": "conv-b2", "lead_id": "lead-b2", "channel_id": "ch-b2",
            "stage": "atacado", "status": "active", "followup_enabled": True}


def _mock_settings():
    s = MagicMock()
    s.ai_phone_number_id = None
    s.ai_phone_number_ids = frozenset()
    return s


@pytest.mark.asyncio
async def test_handoff_during_send_aborts_remaining_sales_bubbles():
    """Se a IA for desligada (handoff concorrente) entre as bolhas, o resto NÃO é enviado."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lock(lead_id):
        yield True

    # get_lead: 1ª checagem (antes da bolha 1) → IA ligada; 2ª checagem → desligada.
    calls = {"n": 0}
    def _get_lead_flip(_lead_id):
        calls["n"] += 1
        return {"id": "lead-b2", "ai_enabled": calls["n"] < 2}

    async def fake_run_agent(conversation, text, **kwargs):
        return "bolha um\n\nbolha dois\n\nbolha tres"

    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={})
    provider.send_image_base64 = AsyncMock(return_value={})

    P = "app.buffer.processor."
    sched = MagicMock()
    patches = [
        patch(P + "get_or_create_lead", return_value=_make_lead()),
        patch(P + "get_lead", side_effect=_get_lead_flip),
        patch(P + "get_channel_by_id", return_value=_make_channel()),
        patch(P + "get_provider", return_value=provider),
        patch(P + "get_or_create_conversation", return_value=_make_conversation()),
        patch(P + "get_active_enrollment", return_value=None),
        patch(P + "save_message"),
        patch(P + "_save_with_retry", new=AsyncMock()),
        patch(P + "run_agent", side_effect=fake_run_agent),
        patch(P + "split_into_bubbles", return_value=["bolha um", "bolha dois", "bolha tres"]),
        patch(P + "_is_recent_duplicate", return_value=False),
        patch(P + "_wamid_already_processed", return_value=False),
        patch(P + "update_conversation"),
        patch(P + "_schedule_followup", sched),
        patch(P + "pop_interest_marked", return_value=None),
        # mídia enfileirada: deve ser DESCARTADA quando o handoff aborta
        patch(P + "pop_deferred_media", return_value=[{"b64": "x", "mimetype": "image/jpeg", "caption": "c"}]),
        patch(P + "_sleep_with_typing_renewal", new=AsyncMock()),
        patch(P + "get_supabase", return_value=MagicMock()),
        patch(P + "run_with_retry"),
        patch(P + "settings", _mock_settings()),
        patch(P + "_check_frustration_guardrail", return_value=False),
        patch(P + "_update_last_msg"),
        patch(P + "resolve_send_target", return_value="+5544991611703"),
        patch(P + "extract_wamid", return_value="w"),
        patch(P + "lead_run_lock", _noop_lock),
    ]

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5544991611703", "quero provar", "ch-b2", wamid="wamid.X")

    # Só a 1ª bolha saiu; bolha dois e três foram abortadas após o handoff.
    assert provider.send_text.call_count == 1
    # Catálogo de fotos NÃO é despejado após o transbordo.
    provider.send_image_base64.assert_not_called()
    # Follow-up não é agendado para um lead já transbordado.
    sched.assert_not_called()
