from app.leads.service import resolve_send_target


def test_resolve_send_target_prefers_wa_id_then_phone_then_bsuid():
    assert resolve_send_target({"wa_id": "16505551234", "phone": "16505551234", "bsuid": "US.1"}) == "16505551234"
    assert resolve_send_target({"phone": "5534999999999", "bsuid": "US.1"}) == "5534999999999"
    assert resolve_send_target({"bsuid": "US.13491208655302741918"}) == "US.13491208655302741918"
    assert resolve_send_target(None, fallback="US.9") == "US.9"


def test_resolve_send_target_empty_phone_falls_to_bsuid():
    assert resolve_send_target({"phone": "", "wa_id": "", "bsuid": "US.7"}) == "US.7"
