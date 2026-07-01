from unittest.mock import patch

from app.webhook.meta_router import _extract_from_number, _extract_statuses, _register_lead


def _msg_payload(message):
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


def test_extract_identity_prefers_phone():
    p = _msg_payload({"from": "5534999999999", "from_user_id": "BR.999"})
    assert _extract_from_number(p) == "5534999999999"


def test_extract_identity_falls_back_to_bsuid():
    p = _msg_payload({"from_user_id": "US.13491208655302741918"})
    assert _extract_from_number(p) == "US.13491208655302741918"


def test_extract_identity_from_status_recipient_user_id():
    p = {"entry": [{"changes": [{"value": {"statuses": [
        {"recipient_user_id": "US.1349", "status": "delivered", "id": "w1"}
    ]}}]}]}
    assert _extract_from_number(p) is None
    statuses = _extract_statuses(p)
    assert (statuses[0].get("recipient_id") or statuses[0].get("recipient_user_id")) == "US.1349"


def test_register_lead_bsuid_only_creates_via_get_or_create():
    """A phone-less (BSUID-only) message registers the lead through get_or_create_lead,
    passing the BSUID; no wa_id is stamped (a BSUID is not a deliverable phone)."""
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "bsuid": "US.1349", "wa_id": None}) as goc, \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("", "Pablo", bsuid="US.1349")
    _, kwargs = goc.call_args
    assert kwargs.get("bsuid") == "US.1349"
    # No wa_id stamping for a BSUID identity.
    assert not any(c.kwargs.get("wa_id") for c in upd.call_args_list)


def test_register_lead_stamps_bsuid_on_existing_phone_lead():
    """Phone lead that lacks a bsuid gets it stamped (merge), so a future username
    adoption (phone omitted) still matches this lead."""
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "phone": "5534999999999", "wa_id": "5534999999999", "bsuid": None}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5534999999999", "Ana", bsuid="BR.999")
    assert any(c.args == ("L1",) and c.kwargs.get("bsuid") == "BR.999" for c in upd.call_args_list)
