from app.webhook.meta_router import _extract_from_number, _extract_statuses


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
