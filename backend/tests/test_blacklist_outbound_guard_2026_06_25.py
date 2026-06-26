"""Defesa em dupla camada contra disparo outbound para a blacklist (2026-06-25).

Critério de blacklist (lead PROIBIDO de receber disparo ativo):
  - leads.opt_out IS TRUE  (hard opt-out canônico — registrar_optout), OU
  - lead tem deal no pipeline "Blacklist" (BLACKLIST_PIPELINE_ID) — cobre o gap de
    leads na Blacklist sem o flag opt_out.
NÃO inclui stage='perdido' (soft rejection — opt_out=false, reativável).

Camada 1: filtro na criação do disparo (router.assign_leads / import_leads).
Camada 2: guardrail no momento do envio (worker._blacklist_guardrail).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.leads.service import BLACKLIST_PIPELINE_ID


def _sb_for_blacklist(opt_out, has_blacklist_deal):
    """Mock supabase: leads.select(opt_out)... e deals.select(id)...(pipeline Blacklist)."""
    sb = MagicMock()
    leads_tbl = MagicMock()
    leads_tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
        [{"opt_out": opt_out}]
    )
    deals_tbl = MagicMock()
    deals_tbl.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
        [{"id": "deal-bl"}] if has_blacklist_deal else []
    )
    sb.table.side_effect = lambda name: leads_tbl if name == "leads" else deals_tbl
    return sb, deals_tbl


# --------------------------------------------------------------------------
# is_lead_blacklisted — núcleo do critério
# --------------------------------------------------------------------------

def test_blacklisted_when_opt_out_true():
    from app.leads.service import is_lead_blacklisted
    sb, _ = _sb_for_blacklist(opt_out=True, has_blacklist_deal=False)
    with patch("app.leads.service.get_supabase", return_value=sb):
        assert is_lead_blacklisted("lead-1") is True


def test_blacklisted_when_in_blacklist_pipeline_even_without_opt_out():
    """Cobre o gap real: lead na Blacklist sem opt_out=true ainda é blacklist."""
    from app.leads.service import is_lead_blacklisted
    sb, deals_tbl = _sb_for_blacklist(opt_out=False, has_blacklist_deal=True)
    with patch("app.leads.service.get_supabase", return_value=sb):
        assert is_lead_blacklisted("lead-2") is True
    # a query de deals deve filtrar pelo pipeline Blacklist correto
    pipeline_eq = deals_tbl.select.return_value.eq.return_value.eq.call_args
    assert pipeline_eq[0] == ("pipeline_id", BLACKLIST_PIPELINE_ID)


def test_not_blacklisted_when_opt_out_false_and_no_blacklist_deal():
    """stage='perdido' (soft) cai aqui: opt_out=false + sem deal na Blacklist → NÃO blacklist."""
    from app.leads.service import is_lead_blacklisted
    sb, _ = _sb_for_blacklist(opt_out=False, has_blacklist_deal=False)
    with patch("app.leads.service.get_supabase", return_value=sb):
        assert is_lead_blacklisted("lead-perdido") is False


def test_not_blacklisted_when_lead_id_empty():
    from app.leads.service import is_lead_blacklisted
    assert is_lead_blacklisted("") is False
    assert is_lead_blacklisted(None) is False


def test_fail_open_false_on_exception():
    """Erro de checagem não bloqueia o disparo (fail-open=False, igual lead_has_active_relationship)."""
    from app.leads.service import is_lead_blacklisted
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch("app.leads.service.get_supabase", return_value=sb):
        assert is_lead_blacklisted("lead-boom") is False


# --------------------------------------------------------------------------
# Camada 2 — guardrail no worker de envio
# --------------------------------------------------------------------------

def test_worker_guardrail_blocks_blacklisted_lead():
    from app.broadcast.worker import _blacklist_guardrail
    with patch("app.broadcast.worker.is_lead_blacklisted", return_value=True):
        reason = _blacklist_guardrail({"id": "lead-x", "phone": "5511999990000"})
    assert reason is not None
    assert "blacklist" in reason.lower()


def test_worker_guardrail_allows_healthy_lead():
    from app.broadcast.worker import _blacklist_guardrail
    with patch("app.broadcast.worker.is_lead_blacklisted", return_value=False):
        assert _blacklist_guardrail({"id": "lead-ok", "phone": "5511999990000"}) is None


# --------------------------------------------------------------------------
# Camada 1 — filtro na criação do disparo (assign_leads)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_leads_skips_blacklisted_and_counts():
    from app.broadcast.router import assign_leads, AssignLeadsRequest
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 1
    with patch("app.broadcast.router.get_supabase", return_value=sb), \
         patch("app.broadcast.router._lead_has_active_relationship", return_value=False), \
         patch("app.broadcast.router._is_lead_blacklisted", side_effect=lambda lid: lid == "bl-1"):
        res = await assign_leads("bc-1", AssignLeadsRequest(lead_ids=["bl-1", "good-1"]))
    assert res["skipped_blacklist"] == 1
    assert res["assigned"] == 1
    # insert só rodou para o lead saudável (1x), nunca para o blacklisted
    assert sb.table.return_value.insert.call_count == 1
