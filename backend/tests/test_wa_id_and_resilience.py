"""Tests for wa_id-based send targeting and Supabase HTTP/2 resilience (retry)."""
import httpx
import pytest
from unittest.mock import patch, MagicMock

from app.leads.service import resolve_send_target
from app.db.supabase import run_with_retry


# --------------------------------------------------------------------------- #
# resolve_send_target — prefer the deliverable wa_id over the normalized phone
# --------------------------------------------------------------------------- #

def test_resolve_send_target_prefers_wa_id():
    lead = {"phone": "5534932262600", "wa_id": "553432262600"}
    # wa_id (12 díg, registrado no WhatsApp) ganha do phone normalizado (13 díg)
    assert resolve_send_target(lead, "ignored") == "553432262600"


def test_resolve_send_target_falls_back_to_phone_when_wa_id_absent_or_empty():
    assert resolve_send_target({"phone": "5511999999999"}, "x") == "5511999999999"
    assert resolve_send_target({"phone": "5511999999999", "wa_id": None}, "x") == "5511999999999"
    assert resolve_send_target({"phone": "5511999999999", "wa_id": ""}, "x") == "5511999999999"


def test_resolve_send_target_uses_fallback_when_no_lead_or_no_phone():
    assert resolve_send_target(None, "5511888888888") == "5511888888888"
    assert resolve_send_target({}, "5511888888888") == "5511888888888"


def test_resolve_send_target_empty_when_nothing_available():
    assert resolve_send_target(None, None) == ""
    assert resolve_send_target({}, None) == ""


# --------------------------------------------------------------------------- #
# run_with_retry — retry only on httpx.TransportError (GOAWAY/conn drops)
# --------------------------------------------------------------------------- #

def test_run_with_retry_returns_immediately_on_success():
    fn = MagicMock(return_value="ok")
    assert run_with_retry(fn, label="t") == "ok"
    assert fn.call_count == 1


def test_run_with_retry_recovers_after_transient_goaway():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            # RemoteProtocolError (GOAWAY) é subclasse de httpx.TransportError
            raise httpx.RemoteProtocolError("GOAWAY ConnectionTerminated")
        return "recovered"

    with patch("app.db.supabase.time.sleep"):
        assert run_with_retry(fn, label="t") == "recovered"
    assert calls["n"] == 2


def test_run_with_retry_gives_up_after_max_attempts():
    fn = MagicMock(side_effect=httpx.ConnectError("connection refused"))
    with patch("app.db.supabase.time.sleep"):
        with pytest.raises(httpx.ConnectError):
            run_with_retry(fn, label="t")
    assert fn.call_count == 3  # _DB_RETRY_ATTEMPTS


def test_run_with_retry_does_not_mask_application_errors():
    # HTTPStatusError / ValueError não são TransportError — não devem ser repetidos
    fn = MagicMock(side_effect=ValueError("4xx app error"))
    with pytest.raises(ValueError):
        run_with_retry(fn, label="t")
    assert fn.call_count == 1


# --------------------------------------------------------------------------- #
# Webhook captures the real wa_id (messages[].from) onto the lead
# --------------------------------------------------------------------------- #

def test_register_lead_captures_wa_id_and_stamps_provenance():
    """Inbound real = prova de tráfego: grava o wa_id E carimba wa_id_confirmed_at."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": None, "wa_id_confirmed_at": None}) as goc, \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("553432262600", "Arthur")
    goc.assert_called_once()
    assert upd.called
    args, kwargs = upd.call_args
    assert args[0] == "L1"
    assert kwargs["wa_id"] == "553432262600"
    assert kwargs["wa_id_confirmed_at"]


def test_register_lead_stamps_provenance_when_confirmed_missing():
    """wa_id igual, mas sem procedência ainda: o inbound carimba wa_id_confirmed_at (sem tocar wa_id)."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "553432262600"}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("553432262600", None)
    assert upd.called
    kwargs = upd.call_args.kwargs
    assert "wa_id" not in kwargs
    assert kwargs["wa_id_confirmed_at"]


def test_register_lead_skips_update_when_already_confirmed():
    """wa_id igual E já confirmado: nada a fazer, nenhum update."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "553432262600",
                             "wa_id_confirmed_at": "2026-07-01T00:00:00+00:00"}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("553432262600", None)
    upd.assert_not_called()
