"""Tests for lp_webhook service."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ─── get_lp_config ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_lp_config_returns_defaults_when_redis_empty():
    """Redis.get returns None → function returns default config."""
    from app.lp_webhook.service import get_lp_config, _DEFAULT_CONFIG

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    result = await get_lp_config(redis)

    assert result == _DEFAULT_CONFIG


@pytest.mark.anyio
async def test_get_lp_config_merges_stored_values():
    """Redis.get returns partial JSON → merged with defaults, stored values win."""
    from app.lp_webhook.service import get_lp_config, _DEFAULT_CONFIG

    stored = {"channel_id": "ch-123", "template_name": "welcome_lp"}
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(stored))

    result = await get_lp_config(redis)

    # stored values override defaults
    assert result["channel_id"] == "ch-123"
    assert result["template_name"] == "welcome_lp"
    # defaults preserved for missing keys
    assert result["language_code"] == _DEFAULT_CONFIG["language_code"]
    assert result["delay_minutes"] == _DEFAULT_CONFIG["delay_minutes"]


# ─── process_landing_page_lead ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_process_lp_lead_invalid_phone_returns_error():
    """Empty whatsapp field → returns error dict with 'Telefone' in message."""
    from app.lp_webhook.service import process_landing_page_lead

    redis = AsyncMock()
    payload = {"whatsapp": "", "nome": "João", "email": "j@x.com", "origem": "lp1"}

    result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is False
    assert "Telefone" in result["error"]


@pytest.mark.anyio
async def test_process_lp_lead_creates_lead_and_conversation():
    """Valid phone + full config → get_or_create_lead, get_or_create_conversation,
    _schedule_lp_welcome all called; returns ok=True with lead_id and conversation_id."""
    from app.lp_webhook.service import process_landing_page_lead

    fake_lead = {"id": "lead-abc", "phone": "5511999990001", "name": "Maria", "email": None, "metadata": {}}
    fake_conv = {"id": "conv-xyz", "lead_id": "lead-abc", "channel_id": "ch-001"}
    fake_config = {
        "channel_id": "ch-001",
        "template_name": "welcome_lp",
        "language_code": "pt_BR",
        "delay_minutes": 15,
    }

    redis = AsyncMock()

    payload = {
        "whatsapp": "5511999990001",
        "nome": "Maria",
        "email": "maria@test.com",
        "origem": "landing-page-atacado",
    }

    with patch("app.lp_webhook.service.normalize_phone", return_value="5511999990001"), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_or_create_conversation", return_value=fake_conv), \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value={"channel_id": "ch-1", "template_name": "boas_vindas", "language_code": "pt_BR", "delay_minutes": 15})), \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb:

        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is True
    assert result["lead_id"] == "lead-abc"
    assert result["conversation_id"] == "conv-xyz"
    mock_schedule.assert_called_once()
    call_kwargs = mock_schedule.call_args
    assert call_kwargs is not None


@pytest.mark.anyio
async def test_process_lp_lead_skips_job_when_config_incomplete():
    """Empty channel_id and template_name → _schedule_lp_welcome NOT called."""
    from app.lp_webhook.service import process_landing_page_lead

    fake_lead = {"id": "lead-abc", "phone": "5511999990001", "name": "Carlos", "email": None, "metadata": {}}
    fake_config = {
        "channel_id": "",
        "template_name": "",
        "language_code": "pt_BR",
        "delay_minutes": 15,
    }

    redis = AsyncMock()

    payload = {
        "whatsapp": "5511999990001",
        "nome": "Carlos",
        "email": "",
        "origem": "",
    }

    with patch("app.lp_webhook.service.normalize_phone", return_value="5511999990001"), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value={"channel_id": "", "template_name": "", "language_code": "pt_BR", "delay_minutes": 15})), \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb:

        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is True
    assert result["lead_id"] == "lead-abc"
    assert result["conversation_id"] is None
    mock_schedule.assert_not_called()


# ─── _schedule_lp_welcome ──────────────────────────────────────────────────────

def test_schedule_lp_welcome_inserts_correct_job():
    """Verifies job fields: job_type='lp_welcome', sequence=1, status='pending',
    correct metadata, fire_at = now + delay_minutes."""
    from app.lp_webhook.service import _schedule_lp_welcome

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: (
        inserted.append(mock_insert.call_args[0][0])
        or MagicMock(data=[{"id": "job-1"}])
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)

    with patch("app.lp_webhook.service.get_supabase", return_value=mock_sb), \
         patch("app.lp_webhook.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        _schedule_lp_welcome(
            conversation_id="conv-1",
            lead_id="lead-1",
            channel_id="ch-1",
            lead_phone="5511999990001",
            template_name="welcome_lp",
            language_code="pt_BR",
            delay_minutes=15,
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["job_type"] == "lp_welcome"
    assert job["sequence"] == 1
    assert job["status"] == "pending"
    assert job["conversation_id"] == "conv-1"
    assert job["lead_id"] == "lead-1"
    assert job["channel_id"] == "ch-1"
    assert job["metadata"]["lead_phone"] == "5511999990001"
    assert job["metadata"]["template_name"] == "welcome_lp"
    assert job["metadata"]["language_code"] == "pt_BR"

    fire_at = datetime.fromisoformat(job["fire_at"])
    expected = now + timedelta(minutes=15)
    assert abs((fire_at - expected).total_seconds()) < 2


# ── _process_lp_welcome (scheduler) ──────────────────────────────────────────

@pytest.mark.anyio
async def test_process_lp_welcome_dispatches_template_and_marks_sent():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-1",
        "lead_id": "lead-1",
        "conversation_id": "conv-1",
        "channel_id": "ch-1",
        "channels": {"id": "ch-1", "provider": "meta_cloud", "provider_config": {"access_token": "tok"}},
        "leads": {"id": "lead-1", "phone": "5534999999999", "last_customer_message_at": None},
        "metadata": {
            "lead_phone": "5534999999999",
            "template_name": "boas_vindas",
            "language_code": "pt_BR",
        },
    }

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock()

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider) as mock_meta, \
         patch("app.follow_up.scheduler._mark_sent") as mock_mark_sent:

        await _process_lp_welcome(job, now)

    mock_provider.send_template.assert_awaited_once_with(
        "5534999999999", "boas_vindas", language_code="pt_BR"
    )
    mock_mark_sent.assert_called_once_with("job-lp-1")


@pytest.mark.anyio
async def test_process_lp_welcome_cancels_when_metadata_missing():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-2",
        "lead_id": "lead-1",
        "channels": {"provider_config": {}},
        "leads": {"id": "lead-1", "phone": "5534999999999", "last_customer_message_at": None},
        "metadata": {},  # missing lead_phone and template_name
    }

    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler.MetaCloudClient") as mock_meta:

        await _process_lp_welcome(job, now)

    mock_cancel.assert_called_once_with("job-lp-2", "missing_metadata")
    mock_meta.assert_not_called()


@pytest.mark.anyio
async def test_process_lp_welcome_cancels_when_lead_already_replied():
    """Se lead já enviou mensagem, job é cancelado sem enviar template."""
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-5",
        "lead_id": "lead-1",
        "channels": {"provider_config": {"phone_number_id": "123", "access_token": "tok"}},
        "leads": {
            "id": "lead-1",
            "phone": "5534999999999",
            "last_customer_message_at": "2026-05-28T10:10:00+00:00",  # lead já respondeu
        },
        "metadata": {
            "lead_phone": "5534999999999",
            "template_name": "boas_vindas",
            "language_code": "pt_BR",
        },
    }

    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler.MetaCloudClient") as mock_meta:

        await _process_lp_welcome(job, now)

    mock_cancel.assert_called_once_with("job-lp-5", "lead_already_replied")
    mock_meta.assert_not_called()


@pytest.mark.anyio
async def test_process_lp_welcome_does_not_mark_sent_on_send_failure():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-3",
        "lead_id": "lead-1",
        "channels": {"provider_config": {}},
        "leads": {"id": "lead-1", "phone": "5534999999999", "last_customer_message_at": None},
        "metadata": {
            "lead_phone": "5534999999999",
            "template_name": "boas_vindas",
            "language_code": "pt_BR",
        },
    }

    mock_provider = AsyncMock()
    mock_provider.send_template.side_effect = Exception("Meta API down")

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider), \
         patch("app.follow_up.scheduler._mark_sent") as mock_mark_sent:

        await _process_lp_welcome(job, now)

    mock_mark_sent.assert_not_called()
