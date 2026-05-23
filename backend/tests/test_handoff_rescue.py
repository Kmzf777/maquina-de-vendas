"""Tests for handoff rescue: schedule_handoff_rescue and _process_handoff_rescue."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ─── schedule_handoff_rescue ────────────────────────────────────────────────

def test_schedule_handoff_rescue_inserts_job_with_correct_fields():
    """Insere job com job_type='handoff_rescue', sequence=0, fire_at=now+15min."""
    from app.follow_up.service import schedule_handoff_rescue

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        schedule_handoff_rescue(
            lead_id="lead-1",
            lead_phone="5511999999999",
            conversation_id="conv-1",
            channel_id="ch-1",
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["job_type"] == "handoff_rescue"
    assert job["sequence"] == 0
    assert job["status"] == "pending"
    assert job["lead_id"] == "lead-1"
    assert job["conversation_id"] == "conv-1"
    assert job["channel_id"] == "ch-1"
    assert job["metadata"]["lead_phone"] == "5511999999999"
    assert job["metadata"]["joao_phone_number_id"] == "1049315514934778"
    assert job["metadata"]["template_name"] == "rabubens"

    fire_at = datetime.fromisoformat(job["fire_at"])
    expected = now + timedelta(minutes=15)
    assert abs((fire_at - expected).total_seconds()) < 2


def test_schedule_handoff_rescue_raises_on_db_error():
    """Erro no insert é propagado como RuntimeError."""
    from app.follow_up.service import schedule_handoff_rescue

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception("db down")

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb):
        with pytest.raises(RuntimeError, match="Falha ao agendar"):
            schedule_handoff_rescue(
                lead_id="lead-1",
                lead_phone="5511999999999",
                conversation_id="conv-1",
                channel_id="ch-1",
            )


# ─── _process_handoff_rescue (via process_due_followups) ────────────────────

def _make_rescue_job():
    return {
        "id": "job-rescue-1",
        "conversation_id": "conv-ai-1",
        "lead_id": "lead-1",
        "channel_id": "ch-ai-1",
        "sequence": 0,
        "job_type": "handoff_rescue",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-ai-1",
            "name": "Canal IA",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
            "mode": "ai",
        },
        "conversations": {"id": "conv-ai-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {
            "lead_phone": "5511999999999",
            "joao_phone_number_id": "1049315514934778",
            "template_name": "rabubens",
        },
    }


@pytest.mark.asyncio
async def test_handoff_rescue_sends_template_when_lead_has_not_contacted_joao():
    """Lead sem nenhuma conversa com canal do João → dispara template rabubens."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    # No conversations between lead and João's channel
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_called_once_with("5511999999999", "rabubens")
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_skips_template_when_lead_already_replied_to_joao():
    """Lead que já enviou msg para João nos últimos 15 min → sem template, job marcado sent."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    conv_result = MagicMock()
    conv_result.data = [{"id": "conv-joao-1"}]
    msg_result = MagicMock()
    msg_result.data = [{"id": "msg-user-1"}]

    def _table(name):
        tbl = MagicMock()
        if name == "conversations":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = conv_result
        elif name == "messages":
            tbl.select.return_value.in_.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = msg_result
        return tbl

    mock_sb.table.side_effect = _table
    mock_meta = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_not_called()
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_cancels_when_joao_channel_not_found():
    """Canal do João inexistente → job cancelado com razão joao_channel_not_found."""
    job = _make_rescue_job()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=None), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-rescue-1", "joao_channel_not_found")
    mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_does_not_mark_sent_if_template_send_fails():
    """Falha no send_template → job NÃO é marcado sent (será retentado no próximo tick)."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(side_effect=RuntimeError("Meta API error"))

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_sent.assert_not_called()
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_standard_jobs_not_affected_by_handoff_rescue_routing():
    """Jobs job_type='standard' continuam sendo processados pelo caminho existente."""
    standard_job = {
        "id": "job-std-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "job_type": "standard",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-1",
            "mode": "ai",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
        },
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[standard_job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi, tudo bem?"), \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_provider.send_text.assert_called_once()
    mock_sent.assert_called_once_with("job-std-1")
    mock_cancel.assert_not_called()
