from app.webhook.meta_parser import parse_meta_webhook_payload


def _payload(contact, message):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "155", "phone_number_id": "PNID"},
                    "contacts": [contact],
                    "messages": [message],
                },
            }],
        }],
    }


def test_username_user_phone_omitted():
    payload = _payload(
        contact={"profile": {"name": "Pablo M.", "username": "pablomorales"},
                 "user_id": "US.13491208655302741918"},
        message={"from_user_id": "US.13491208655302741918", "id": "w1",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == ""
    assert msgs[0].bsuid == "US.13491208655302741918"
    assert msgs[0].username == "pablomorales"
    assert msgs[0].push_name == "Pablo M."


def test_username_user_phone_present():
    payload = _payload(
        contact={"profile": {"name": "Pablo M.", "username": "pablomorales"},
                 "wa_id": "16505551234", "user_id": "US.1349"},
        message={"from": "16505551234", "from_user_id": "US.1349", "id": "w2",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert msgs[0].from_number == "16505551234"
    assert msgs[0].bsuid == "US.1349"
    assert msgs[0].username == "pablomorales"


def test_no_username_user_bsuid_and_phone():
    payload = _payload(
        contact={"profile": {"name": "Ana"}, "wa_id": "5534999999999", "user_id": "BR.999"},
        message={"from": "5534999999999", "from_user_id": "BR.999", "id": "w3",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].bsuid == "BR.999"
    assert msgs[0].username is None
    assert msgs[0].push_name == "Ana"
