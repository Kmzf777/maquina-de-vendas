"""Procedência do wa_id, captura do endereço canônico e retentativa por 9º dígito.

Contexto: o disparo frio ficava aceito-mas-não-entregue porque resolve_send_target
confiava num wa_id de 12 dígitos SEM procedência (plantado por harness/obsoleto). Estes
testes fixam o gate estrito de procedência, o aprendizado do contacts[0].wa_id no envio,
e a alternância do 9º dígito da dupla tentativa.
"""

from unittest.mock import MagicMock, patch

from app.leads.service import resolve_send_target, has_wa_id_provenance
from app.broadcast.worker import _toggle_br_ninth_digit, _capture_canonical_wa_id


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


# ─── _capture_canonical_wa_id ────────────────────────────────────────────────

def test_capture_persists_canonical_wa_id():
    lead = {"id": "L1", "wa_id": None, "wa_id_confirmed_at": None}
    resp = {"contacts": [{"input": "5534996652412", "wa_id": "553496652412"}],
            "messages": [{"id": "wamid.x"}]}
    with patch("app.broadcast.worker.update_lead") as upd:
        _capture_canonical_wa_id(lead, resp)
    assert upd.called
    kwargs = upd.call_args.kwargs
    assert kwargs["wa_id"] == "553496652412"
    assert kwargs["wa_id_confirmed_at"]


def test_capture_noop_when_already_confirmed_same():
    lead = {"id": "L1", "wa_id": "553496652412", "wa_id_confirmed_at": "2026-07-06T00:00:00+00:00"}
    resp = {"contacts": [{"wa_id": "553496652412"}]}
    with patch("app.broadcast.worker.update_lead") as upd:
        _capture_canonical_wa_id(lead, resp)
    assert not upd.called


def test_capture_ignores_missing_contacts():
    lead = {"id": "L1", "wa_id": None}
    with patch("app.broadcast.worker.update_lead") as upd:
        _capture_canonical_wa_id(lead, {"messages": [{"id": "wamid.x"}]})
    assert not upd.called
