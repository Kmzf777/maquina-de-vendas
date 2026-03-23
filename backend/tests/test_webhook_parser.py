from app.webhook.parser import parse_webhook_payload


def test_parse_text_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5534999999999",
                        "id": "wamid.abc123",
                        "timestamp": "1234567890",
                        "type": "text",
                        "text": {"body": "oi, quero saber dos cafes"}
                    }]
                }
            }]
        }]
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].type == "text"
    assert msgs[0].text == "oi, quero saber dos cafes"
    assert msgs[0].media_id is None


def test_parse_audio_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5534999999999",
                        "id": "wamid.abc456",
                        "timestamp": "1234567890",
                        "type": "audio",
                        "audio": {"id": "media_id_123", "mime_type": "audio/ogg"}
                    }]
                }
            }]
        }]
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "audio"
    assert msgs[0].media_id == "media_id_123"


def test_parse_empty_payload():
    payload = {"object": "whatsapp_business_account", "entry": []}
    msgs = parse_webhook_payload(payload)
    assert msgs == []
