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
