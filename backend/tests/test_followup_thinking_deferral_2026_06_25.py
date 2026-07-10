"""Auditoria forense leads 5566999975586 (Alessandro) e 5531996039118 (Gustavo), 2026-06-25.

Dois bugs no follow-up `standard`:

1. TÉCNICO (corte): `_generate_followup_message` chamava gemini-2.5-flash com teto de 1024
   e SEM desligar o thinking. O thinking devorava o budget → corte por budget (na época
   finish_reason="length"; no núcleo nativo o nome é "MAX_TOKENS") → mensagem entregue pela
   metade ("...o que te fez pensar em"). Mesma cura já aplicada no orchestrator (thinking
   off + 4096) nunca foi propagada aqui. Sem rastro de token_usage.

2. COMPORTAMENTAL (robô surdo): o cliente disse "estou em viagem essa semana, mas na próxima
   já estarei mais tranquilo" e o follow-up disparou ~1h42 depois, ignorando o adiamento.
   O prompt agora obriga o LLM a devolver [ADIAMENTO_DETECTADO] nesses casos, e o scheduler
   aborta silenciosamente.
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from tests.gemini_fakes import fake_text, fake_usage


def _make_job():
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "id": "job-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {"id": "lead-1", "phone": "+5566999975586", "last_customer_message_at": now_iso},
        "channels": {
            "id": "ch-1", "name": "Canal Comercial", "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}, "mode": "ai",
        },
        "conversations": {
            "id": "conv-1", "stage": "atacado", "followup_enabled": True,
            "last_customer_message_at": now_iso,
        },
    }


def _sb_with_history():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"role": "user", "content": "Sim, estou em viagem essa semana, mas na próxima ja estarei mais tranquilo"},
    ]
    return sb


# === 1. Correção técnica: thinking off + cap 4096 + finish_reason ==========

@pytest.mark.asyncio
async def test_generate_followup_disables_thinking_and_raises_cap():
    """A chamada do Gemini no follow-up DEVE desligar o thinking e usar teto de 4096."""
    m_gen = AsyncMock(return_value=fake_text("oi sobre o cafe", usage=fake_usage(100, 40)))

    with patch("app.follow_up.scheduler.generate", new=m_gen), \
         patch("app.follow_up.scheduler.track_token_usage"):
        from app.follow_up.scheduler import _generate_followup_message
        text, finish = await _generate_followup_message(
            [{"role": "user", "content": "oi"}], 1, lead_id="lead-1", stage="atacado"
        )

    kwargs = m_gen.await_args.kwargs
    assert kwargs["max_output_tokens"] == 4096
    assert kwargs["thinking_off"] is True
    assert text == "oi sobre o cafe"
    assert finish == "STOP"


@pytest.mark.asyncio
async def test_generate_followup_records_token_usage():
    """O custo do follow-up DEVE ser gravado em token_usage (antes não era rastreado)."""
    m_gen = AsyncMock(return_value=fake_text("oi", usage=fake_usage(123, 45)))

    with patch("app.follow_up.scheduler.generate", new=m_gen), \
         patch("app.follow_up.scheduler.track_token_usage") as mock_track:
        from app.follow_up.scheduler import _generate_followup_message
        await _generate_followup_message(
            [{"role": "user", "content": "oi"}], 1, lead_id="lead-1", stage="atacado"
        )

    mock_track.assert_called_once()
    kw = mock_track.call_args.kwargs
    assert kw["lead_id"] == "lead-1"
    assert kw["prompt_tokens"] == 123
    assert kw["completion_tokens"] == 45
    assert kw["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_length_finish_reason_aborts_and_cancels():
    """finish_reason='MAX_TOKENS' → NUNCA enviar mensagem pela metade; cancela o job."""
    job = _make_job()
    truncada = "a gente tinha falado sobre o cafe da Canastra\no que te fez pensar em"
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=_sb_with_history()), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._generate_followup_message",
               return_value=(truncada, "MAX_TOKENS")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_called_once_with("job-1", "length_truncated")
        mock_sent.assert_not_called()
        mock_provider.send_text.assert_not_called()


# === 2. Correção comportamental: válvula de adiamento ======================

@pytest.mark.asyncio
async def test_deferral_marker_cancels_silently_without_send():
    """[ADIAMENTO_DETECTADO]: cliente pediu p/ ser contatado depois → não envia nada."""
    job = _make_job()
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=_sb_with_history()), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._generate_followup_message",
               return_value=("[ADIAMENTO_DETECTADO]", "STOP")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_called_once_with("job-1", "deferral_detected")
        mock_sent.assert_not_called()
        mock_provider.send_text.assert_not_called()


# === 3. Higiene do prompt ==================================================

def test_reengage_instruction_drops_name_prohibition_and_adds_deferral_directive():
    """Sem conflito com base.py (que permite nome na retomada) + diretriz de adiamento."""
    from app.follow_up.scheduler import _FOLLOWUP_REENGAGE_INSTRUCTION as instr
    # Válvula de escape comportamental presente
    assert "[ADIAMENTO_DETECTADO]" in instr
    # Proibição de nome removida (deixa base.py ditar a regra — evita conflito cognitivo)
    assert "nome do lead no começo" not in instr
    assert "fabrizio" not in instr.lower()
