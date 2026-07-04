"""Idempotência dos follow-up jobs via wamid persistido (2026-07-04).

Fecha a janela residual de envio duplicado: o claim atômico impede que dois workers
processem o MESMO job, mas se UM worker envia à Meta e morre ANTES do _mark_sent, a
crash-recovery (cutoff 5min) devolvia o job p/ 'pending' → reenvio cego. Espelhando
broadcast_leads.wamid: o handler persiste o wamid do envio no job antes de marcar
terminal; a recovery, ao ver wamid presente, conclui o job como 'sent' (já despachado)
em vez de reenviar.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.follow_up import scheduler as S


# ─── _save_followup_wamid ────────────────────────────────────────────────────

def test_save_followup_wamid_persiste_quando_presente():
    mock_sb = MagicMock()
    with patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb):
        S._save_followup_wamid("job-1", "wamid.abc")
    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload == {"wamid": "wamid.abc"}
    mock_sb.table.return_value.update.return_value.eq.assert_called_with("id", "job-1")


def test_save_followup_wamid_noop_sem_wamid():
    """Provider sem id (wamid vazio/None) → não escreve nada (não há o que deduplicar)."""
    mock_sb = MagicMock()
    with patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb):
        S._save_followup_wamid("job-1", None)
        S._save_followup_wamid("job-1", "")
    mock_sb.table.assert_not_called()


# ─── crash-recovery ciente do wamid (idempotência) ───────────────────────────

def test_recover_conclui_sent_com_wamid_e_requeue_sem_wamid():
    """Dois ramos (espelho de broadcast): 'processing' antigo COM wamid → 'sent' (não
    reenvia); SEM wamid → 'pending' (nunca enviou, retenta)."""
    mock_sb = MagicMock()
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    with patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb):
        S._recover_stale_followup_jobs(now, stale_minutes=5)

    upd = mock_sb.table.return_value.update
    statuses = [c.args[0]["status"] for c in upd.call_args_list]
    assert "sent" in statuses, "ramo idempotente (wamid presente) deve marcar 'sent'"
    assert "pending" in statuses, "ramo sem envio (wamid nulo) deve requeue p/ 'pending'"

    filt = mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.lt.return_value.filter
    filter_args = [c.args for c in filt.call_args_list]
    assert ("wamid", "not.is", "null") in filter_args  # ramo 'sent'
    assert ("wamid", "is", "null") in filter_args       # ramo 'pending'


# ─── integração: o handler standard persiste o wamid antes de marcar sent ────

@pytest.mark.asyncio
async def test_standard_followup_persiste_wamid_antes_de_marcar_sent():
    job = {
        "id": "job-std-1", "job_type": "standard", "conversation_id": "conv-1",
        "lead_id": "lead-1", "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5511999999999"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": datetime.now(timezone.utc).isoformat()},
        "metadata": {},
    }
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.STD"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._generate_followup_message",
               new=AsyncMock(return_value=("Oi, tudo bem?", "stop"))), \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._save_followup_wamid") as mock_save_wamid, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_save_wamid.assert_called_once_with("job-std-1", "wamid.STD")
    mock_sent.assert_called_once_with("job-std-1")


@pytest.mark.asyncio
async def test_handoff_rescue_persiste_wamid_antes_de_marcar_sent():
    job = {
        "id": "job-rescue-1", "conversation_id": "conv-ai-1", "lead_id": "lead-1",
        "channel_id": "ch-ai-1", "sequence": 1, "job_type": "handoff_rescue",
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Pedro Souza",
                  "last_customer_message_at": datetime.now(timezone.utc).isoformat()},
        "channels": {"id": "ch-ai-1", "name": "Canal IA", "provider": "meta_cloud",
                     "provider_config": {"phone_number_id": "111", "access_token": "tok"}, "mode": "ai"},
        "conversations": {"id": "conv-ai-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {"lead_phone": "5511999999999", "joao_phone_number_id": "1049315514934778",
                     "template_name": "rabubens"},
    }
    joao_channel = {"id": "ch-joao-1", "provider": "meta_cloud",
                    "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"}}
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.RESCUE"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.get_or_create_conversation", return_value={"id": "conv-joao-1"}), \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._save_followup_wamid") as mock_save_wamid, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_save_wamid.assert_called_once_with("job-rescue-1", "wamid.RESCUE")
    mock_sent.assert_called_once_with("job-rescue-1")
