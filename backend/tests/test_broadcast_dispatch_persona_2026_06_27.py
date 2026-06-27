"""Fix 1c: o broadcast propaga a persona (prompt_key) do disparo para o dispatch_metadata.

Assim, um disparo sob a persona valeria_outbound grava intent=cold_reactivation no
cold-open — que a resolução de persona (sticky outbound) usa para manter a conversa
em outbound. Caso real: broadcast DSP-FRIOS-27-06-09-30 (template generico utilidade_*).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import app.broadcast.worker as worker_module


def test_resolve_broadcast_prompt_key_le_do_agent_profile():
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .limit.return_value.execute.return_value) = MagicMock(
        data=[{"prompt_key": "valeria_outbound"}]
    )
    assert worker_module._resolve_broadcast_prompt_key(sb, "ap-out") == "valeria_outbound"


def test_resolve_broadcast_prompt_key_sem_profile_e_none():
    assert worker_module._resolve_broadcast_prompt_key(MagicMock(), None) is None


def test_resolve_broadcast_prompt_key_failopen_none():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    assert worker_module._resolve_broadcast_prompt_key(sb, "ap-out") is None


def test_cold_open_sob_outbound_grava_intent_cold_reactivation():
    """O save do cold-open usa dispatch_metadata com a persona outbound → intent cold."""
    broadcast = {
        "id": "bc-1",
        "status": "running",
        "template_name": "utilidade_22_04_2026_16_40",
        "template_variables": {},
        "channel_id": "ch-1",
        "agent_profile_id": "ap-outbound",
        "send_interval_min": 0,
        "send_interval_max": 0,
    }
    lead = {"id": "lead-1", "phone": "5511999990000"}
    broadcast_lead = {"id": "bl-1", "leads": lead}
    mock_conv = {"id": "conv-1", "stage": "secretaria"}
    mock_provider = MagicMock()
    mock_provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid-1"}]})

    mock_sb = MagicMock()
    # recheck de status do broadcast no loop por-lead deve ver "running" (senão pula o envio)
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0
    captured = {}

    def _capture_save(*args, **kwargs):
        captured["metadata"] = kwargs.get("metadata")
        return {"id": "msg-1"}

    with patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[broadcast_lead]), \
         patch("app.broadcast.worker.mark_broadcast_lead_sent"), \
         patch("app.broadcast.worker.increment_broadcast_sent"), \
         patch("app.broadcast.worker.save_broadcast_lead_wamid"), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-1"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.get_or_create_conversation", return_value=mock_conv), \
         patch("app.broadcast.worker.update_conversation"), \
         patch("app.broadcast.worker.record_dispatch_note"), \
         patch("app.broadcast.worker._render_template_body", new=AsyncMock(return_value="corpo")), \
         patch("app.broadcast.worker.save_message", side_effect=_capture_save), \
         patch("app.broadcast.worker._resolve_broadcast_prompt_key", return_value="valeria_outbound"), \
         patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        asyncio.run(worker_module.process_single_broadcast(broadcast))

    assert captured.get("metadata") is not None, "save_message não foi chamado com metadata"
    assert captured["metadata"]["dispatch"]["intent"] == "cold_reactivation"
