"""Guarda de etapa: o enrollment morre quando o card sai da coluna de gatilho."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.automation.engine import _guard_broken, _process_one


def _sb_com_deal_em(stage_id):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .limit.return_value.execute.return_value.data) = [{"id": "d1", "stage_id": stage_id}]
    return sb


class TestGuardBroken:
    def test_sem_guarda_nunca_quebra(self):
        assert _guard_broken({"metadata": {}}) is False
        assert _guard_broken({}) is False

    def test_card_na_mesma_etapa_nao_quebra(self):
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=_sb_com_deal_em("s1")):
            assert _guard_broken(enr) is False

    def test_card_mudou_de_etapa_quebra(self):
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=_sb_com_deal_em("s2")):
            assert _guard_broken(enr) is True

    def test_deal_apagado_quebra(self):
        sb = MagicMock()
        (sb.table.return_value.select.return_value.eq.return_value
           .limit.return_value.execute.return_value.data) = []
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            assert _guard_broken(enr) is True

    def test_erro_de_banco_nao_quebra(self):
        # Fail-open: erro de leitura nao pode matar esteira legitima.
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("boom")
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            assert _guard_broken(enr) is False


@pytest.mark.asyncio
async def test_process_one_cancela_quando_a_guarda_quebra():
    enrollment = {
        "id": "e1",
        "lead_id": "lead1",
        "deal_id": "d1",
        "step_count": 0,
        "metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}},
        "leads": {"id": "lead1", "phone": "5511999", "ai_enabled": False},
        "campaigns": {"id": "c1", "status": "active", "audience": "humano", "channel_id": "ch1"},
        "campaign_nodes": {"id": "n1", "type": "end", "config": {}},
    }
    with (
        patch("app.automation.engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.engine._guard_broken", return_value=True),
        patch("app.automation.engine._update") as mock_update,
        patch("app.automation.engine._complete") as mock_complete,
        patch("app.automation.engine._log_exec"),
    ):
        await _process_one(enrollment, datetime.now(timezone.utc))
    mock_complete.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "cancelled"


def test_create_enrollment_grava_metadata():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "e1"}]
    with (
        patch("app.campaigns.service.get_supabase", return_value=sb),
        patch("app.campaigns.service.emit_event"),
    ):
        service.create_enrollment(
            "c1", "lead1", "n1", datetime.now(timezone.utc),
            deal_id="d1", metadata={"guard": {"deal_id": "d1", "stage_id": "s1"}},
        )
    payload = sb.table.return_value.insert.call_args[0][0]
    assert payload["metadata"]["guard"]["stage_id"] == "s1"
