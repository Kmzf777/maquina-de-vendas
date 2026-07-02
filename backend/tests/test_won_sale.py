"""Tests for the won-sale service (mark_deal_won) and the POST /api/leads/{id}/won endpoint."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Service — mark_deal_won updates the deal to 'ganho' and returns the lead
# --------------------------------------------------------------------------- #

def test_mark_deal_won_updates_deal_and_returns_lead():
    from app.campaigns import sales

    captured = {}

    deals_table = MagicMock()
    deals_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"id": "D1", "pipeline_id": "P1"}])
    )

    def deals_update(payload):
        captured["update"] = payload
        return MagicMock(eq=MagicMock(return_value=MagicMock(execute=MagicMock())))

    deals_table.update.side_effect = deals_update

    stages_table = MagicMock()
    stages_table.select.return_value.eq.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"id": "S1", "key": "ganho"}])
    )

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: {"deals": deals_table, "pipeline_stages": stages_table}[name]

    with patch("app.campaigns.sales.get_supabase", return_value=mock_sb), \
         patch("app.campaigns.sales.get_lead", return_value={"id": "L1", "ctwa_clid": "c"}):
        result = sales.mark_deal_won("L1", value=150.0, currency="BRL")

    assert result["deals_updated"] == 1
    assert result["lead"] == {"id": "L1", "ctwa_clid": "c"}
    assert result["deal_id"] == "D1"
    assert captured["update"]["stage"] == "ganho"
    assert captured["update"]["value"] == 150.0
    assert captured["update"]["stage_id"] == "S1"
    assert "closed_at" in captured["update"]


# --------------------------------------------------------------------------- #
# Endpoint — marks won synchronously, schedules fire_stage_conversion as BackgroundTask
# --------------------------------------------------------------------------- #

def test_won_endpoint_schedules_dispatch_and_returns_ok():
    from fastapi import BackgroundTasks
    from app.leads.router import mark_lead_won, WonSalePayload

    bg = BackgroundTasks()
    with patch("app.leads.service.get_lead", return_value={"id": "L1"}), \
         patch("app.campaigns.sales.mark_deal_won",
               return_value={"lead": {"id": "L1", "ctwa_clid": "c"}, "deals_updated": 1,
                             "deal_id": "D1"}) as mdw:
        resp = asyncio.run(mark_lead_won("L1", WonSalePayload(value=99.0, currency="BRL"), bg))

    assert resp == {"status": "ok", "deals_updated": 1}
    mdw.assert_called_once()
    # Disparo da conversão foi agendado fora do caminho crítico (não chamado inline).
    assert len(bg.tasks) == 1


def test_won_endpoint_404_when_lead_missing():
    from fastapi import BackgroundTasks, HTTPException
    from app.leads.router import mark_lead_won, WonSalePayload

    with patch("app.leads.service.get_lead", return_value=None):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(mark_lead_won("missing", WonSalePayload(), BackgroundTasks()))
    assert exc.value.status_code == 404


def test_won_endpoint_fires_purchase_via_orchestrator():
    """mark_deal_won returns deal_id 'D1' → /won schedules fire_stage_conversion with event='purchase' and deal_id='D1'."""
    from fastapi import BackgroundTasks
    from app.leads.router import mark_lead_won, WonSalePayload

    bg = BackgroundTasks()
    lead_data = {"id": "L1", "ctwa_clid": "abc123"}

    # fire_stage_conversion is imported locally inside the endpoint, so patch at the source module.
    with patch("app.leads.service.get_lead", return_value=lead_data), \
         patch("app.campaigns.sales.mark_deal_won",
               return_value={"lead": lead_data, "deals_updated": 1, "deal_id": "D1",
                             "value": 99.0, "currency": "BRL"}), \
         patch("app.campaigns.conversions.fire_stage_conversion") as mock_fsc:
        resp = asyncio.run(mark_lead_won("L1", WonSalePayload(value=99.0, currency="BRL"), bg))

    assert resp == {"status": "ok", "deals_updated": 1}
    # Exactly one background task scheduled.
    assert len(bg.tasks) == 1
    task = bg.tasks[0]
    # Positional args: lead, deal_id, event
    assert task.args[1] == "D1"
    assert task.args[2] == "purchase"


def test_won_endpoint_no_background_task_when_no_deal_id():
    """If mark_deal_won returns no deal_id (e.g. no deal found), no background task is scheduled."""
    from fastapi import BackgroundTasks
    from app.leads.router import mark_lead_won, WonSalePayload

    bg = BackgroundTasks()
    lead_data = {"id": "L1"}

    with patch("app.leads.service.get_lead", return_value=lead_data), \
         patch("app.campaigns.sales.mark_deal_won",
               return_value={"lead": lead_data, "deals_updated": 0, "deal_id": None,
                             "value": None, "currency": "BRL"}):
        resp = asyncio.run(mark_lead_won("L1", WonSalePayload(), bg))

    assert resp == {"status": "ok", "deals_updated": 0}
    assert len(bg.tasks) == 0
