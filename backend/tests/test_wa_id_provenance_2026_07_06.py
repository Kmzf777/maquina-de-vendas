"""Procedência do wa_id, captura do endereço canônico e retentativa por 9º dígito.

Contexto: o disparo frio ficava aceito-mas-não-entregue porque resolve_send_target
confiava num wa_id de 12 dígitos SEM procedência (plantado por harness/obsoleto). Estes
testes fixam o gate estrito de procedência, o aprendizado do contacts[0].wa_id no envio,
e a alternância do 9º dígito da dupla tentativa.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.leads.service import resolve_send_target, has_wa_id_provenance
from app.broadcast.worker import _toggle_br_ninth_digit


# ─── resolve_send_target: gate de procedência ────────────────────────────────

def test_strict_ignores_unconfirmed_wa_id():
    lead = {"phone": "5534996652412", "wa_id": "553496652412"}  # sem procedência
    assert resolve_send_target(lead, require_inbound_provenance=True) == "5534996652412"


def test_strict_trusts_wa_id_with_last_customer_message():
    lead = {"phone": "5534996652412", "wa_id": "553496652412",
            "last_customer_message_at": "2026-07-01T10:00:00+00:00"}
    assert resolve_send_target(lead, require_inbound_provenance=True) == "553496652412"


def test_strict_trusts_wa_id_with_confirmed_marker():
    lead = {"phone": "5534996652412", "wa_id": "553496652412",
            "wa_id_confirmed_at": "2026-07-06T19:00:00+00:00"}
    assert resolve_send_target(lead, require_inbound_provenance=True) == "553496652412"


def test_warm_default_preserves_legacy_behavior():
    """Sem o flag estrito (caminho quente), confia no wa_id presente — sem regressão."""
    lead = {"phone": "5511999998888", "wa_id": "551188887777"}
    assert resolve_send_target(lead) == "551188887777"


def test_no_wa_id_falls_back_to_phone_both_modes():
    lead = {"phone": "5511999998888", "wa_id": None}
    assert resolve_send_target(lead) == "5511999998888"
    assert resolve_send_target(lead, require_inbound_provenance=True) == "5511999998888"


def test_has_provenance_helper():
    assert has_wa_id_provenance({"last_customer_message_at": "x"}) is True
    assert has_wa_id_provenance({"wa_id_confirmed_at": "x"}) is True
    assert has_wa_id_provenance({"wa_id": "553496652412"}) is False
    assert has_wa_id_provenance(None) is False


# ─── _toggle_br_ninth_digit ──────────────────────────────────────────────────

def test_toggle_removes_ninth_digit():
    assert _toggle_br_ninth_digit("5534996652412") == "553496652412"


def test_toggle_adds_ninth_digit():
    assert _toggle_br_ninth_digit("553496652412") == "5534996652412"


def test_toggle_roundtrip():
    assert _toggle_br_ninth_digit(_toggle_br_ninth_digit("5534996652412")) == "5534996652412"


def test_toggle_non_br_returns_none():
    assert _toggle_br_ninth_digit("14155552671") is None
    assert _toggle_br_ninth_digit(None) is None


# ─── procedência SÓ por prova assíncrona (webhook delivered/read) ─────────────

def _delivery_sb(lead_id="L1"):
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"lead_id": lead_id}] if lead_id else []
    )
    return sb


@pytest.mark.asyncio
async def test_delivered_webhook_stamps_provenance_and_adopts_recipient():
    """delivered comprova tráfego → carimba wa_id_confirmed_at e adota o recipient_id."""
    from app.webhook.meta_router import _handle_delivery_status
    sb = _delivery_sb("L1")
    with patch("app.webhook.meta_router.get_supabase", return_value=sb), \
         patch("app.webhook.meta_router.update_lead") as upd, \
         patch("app.broadcast.service.find_broadcast_lead_by_wamid", return_value=None):
        await _handle_delivery_status("wamid.x", "delivered", [], "553496652412")
    assert upd.called
    kwargs = upd.call_args.kwargs
    assert kwargs["wa_id"] == "553496652412"
    assert kwargs["wa_id_confirmed_at"]


@pytest.mark.asyncio
async def test_accepted_or_sent_status_does_not_confirm():
    """Status 'sent' (aceite/roteamento) NÃO confere procedência — só delivered/read."""
    from app.webhook.meta_router import _handle_delivery_status
    sb = _delivery_sb("L1")
    with patch("app.webhook.meta_router.get_supabase", return_value=sb), \
         patch("app.webhook.meta_router.update_lead") as upd:
        await _handle_delivery_status("wamid.x", "sent", [], "553496652412")
    assert not upd.called
