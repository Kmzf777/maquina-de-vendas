"""Reivindicação atômica (atomic claim) dos follow-up jobs (2026-07-04).

Auditoria: get_due_followups lê jobs 'pending' e os handlers só escrevem status no
fim (_mark_sent/_cancel_job). Não há claim — se o worker de follow-up for escalado
para N réplicas, todas processam o MESMO job → template/mensagem duplicados. O
broadcast já resolve isso com claim atômico (pending→processing guardado por status)
+ crash-recovery. Espelhamos esse padrão para o follow-up.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.follow_up import scheduler as S


# ─── _claim_followup_job: reivindicação atômica ──────────────────────────────

def test_claim_retorna_true_quando_vence_a_corrida():
    """UPDATE guardado por status='pending' retorna linha → este worker venceu."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "job-1"}
    ]
    with patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb):
        assert S._claim_followup_job("job-1") is True

    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload["status"] == "processing"


def test_claim_retorna_false_quando_outro_worker_ja_pegou():
    """Sem linha retornada (status já não era 'pending') → outro worker venceu."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    with patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb):
        assert S._claim_followup_job("job-1") is False


# A crash-recovery (que agora é ciente do wamid: 'sent' se despachado, 'pending' se não)
# é coberta em test_followup_wamid_idempotencia_2026_07_04.py.


# ─── process_due_followups: claim antes de processar ─────────────────────────

@pytest.mark.asyncio
async def test_process_due_followups_pula_job_quando_claim_perdido():
    """Se o claim falha (outro worker pegou), o job NÃO é processado (sem envio)."""
    job = {
        "id": "job-lost", "job_type": "standard", "conversation_id": "conv-1",
        "lead_id": "lead-1", "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5511999999999"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "followup_enabled": True,
                           "last_customer_message_at": datetime.now(timezone.utc).isoformat()},
        "metadata": {},
    }
    mock_provider = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=False) as mock_claim, \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_claim.assert_called_once_with("job-lost")
    mock_provider.send_text.assert_not_called()
    mock_sent.assert_not_called()
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_process_due_followups_reivindica_antes_de_processar():
    """Claim vencido → o job segue para o processamento normal (claim chamado com o id)."""
    job = {
        "id": "job-won", "job_type": "standard", "conversation_id": "conv-1",
        "lead_id": "lead-1", "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5511999999999"},
        "channels": {"id": "ch-1", "mode": "human", "provider_config": {}},  # human → cancela cedo (sem rede)
        "conversations": {"id": "conv-1", "followup_enabled": True,
                           "last_customer_message_at": datetime.now(timezone.utc).isoformat()},
        "metadata": {},
    }

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True) as mock_claim, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_claim.assert_called_once_with("job-won")
    # canal humano → job cancelado (prova que passou do claim para o processamento)
    mock_cancel.assert_called_once_with("job-won", "human_channel")
