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
# Endpoint — marca a venda como ganha. A conversão de compra NÃO sai daqui: a varredura
# de app/conversions/sweep.py acha a venda e enfileira em ad_conversions.
# --------------------------------------------------------------------------- #

def test_won_endpoint_marks_won_and_returns_ok():
    from app.leads.router import mark_lead_won, WonSalePayload

    with patch("app.leads.service.get_lead", return_value={"id": "L1"}), \
         patch("app.campaigns.sales.mark_deal_won",
               return_value={"lead": {"id": "L1", "ctwa_clid": "c"}, "deals_updated": 1,
                             "deal_id": "D1"}) as mdw, \
         patch("app.leads.reposicao.ensure_reposicao_deal") as erd:
        resp = asyncio.run(mark_lead_won("L1", WonSalePayload(value=99.0, currency="BRL")))

    assert resp == {"status": "ok", "deals_updated": 1}
    mdw.assert_called_once_with("L1", value=99.0, currency="BRL", deal_id=None)
    erd.assert_called_once_with("L1", deal_id="D1")


def test_won_endpoint_404_when_lead_missing():
    from fastapi import HTTPException
    from app.leads.router import mark_lead_won, WonSalePayload

    with patch("app.leads.service.get_lead", return_value=None):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(mark_lead_won("missing", WonSalePayload()))
    assert exc.value.status_code == 404


def test_won_endpoint_sem_deal_nao_chama_reposicao():
    """mark_deal_won sem deal atualizado → não garante card de reposição."""
    from app.leads.router import mark_lead_won, WonSalePayload

    with patch("app.leads.service.get_lead", return_value={"id": "L1"}), \
         patch("app.campaigns.sales.mark_deal_won",
               return_value={"lead": {"id": "L1"}, "deals_updated": 0, "deal_id": None,
                             "value": None, "currency": "BRL"}), \
         patch("app.leads.reposicao.ensure_reposicao_deal") as erd:
        resp = asyncio.run(mark_lead_won("L1", WonSalePayload()))

    assert resp == {"status": "ok", "deals_updated": 0}
    erd.assert_not_called()


def test_won_endpoint_nao_dispara_conversao():
    """O caminho antigo (campaigns/conversions.py) foi removido; o módulo não pode voltar."""
    import importlib.util
    assert importlib.util.find_spec("app.campaigns.conversions") is None
    assert importlib.util.find_spec("app.campaigns.capi_dispatcher") is None
