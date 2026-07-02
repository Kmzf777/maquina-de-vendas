from unittest.mock import MagicMock, patch
import asyncio
from app.automation import triggers


def _run(coro):
    return asyncio.run(coro)


def test_deal_stage_enter_fires_stage_conversion_when_stage_mapped():
    deal_row = {"id": "D1", "lead_id": "L1", "stage_id": "S1"}
    stage_row = {"conversion_event": "qualified", "conversion_value": 50}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [deal_row]
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = stage_row
    with patch("app.automation.triggers.get_supabase", return_value=sb), \
         patch("app.automation.triggers.get_lead", return_value={"id": "L1"}), \
         patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]), \
         patch("app.automation.triggers.fire_stage_conversion_background") as fire:
        _run(triggers.fire_trigger("deal_stage_enter", "L1", {"stage": "qualificado", "deal_id": "D1"}))
    fire.assert_called_once()
    args, kwargs = fire.call_args
    assert args[1] == "D1" and args[2] == "qualified"


def test_deal_stage_enter_no_fire_when_stage_unmapped():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "D1", "lead_id": "L1", "stage_id": "S1"}]
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"conversion_event": None, "conversion_value": None}
    with patch("app.automation.triggers.get_supabase", return_value=sb), \
         patch("app.automation.triggers.get_lead", return_value={"id": "L1"}), \
         patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]), \
         patch("app.automation.triggers.fire_stage_conversion_background") as fire:
        _run(triggers.fire_trigger("deal_stage_enter", "L1", {"stage": "x", "deal_id": "D1"}))
    fire.assert_not_called()
