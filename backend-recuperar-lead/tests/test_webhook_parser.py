from app.webhook.parser import parse_webhook_payload


def test_parse_text_message():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "3EB0BF8072876BE899FE20"
            },
            "pushName": "Joao",
            "message": {
                "conversation": "oi, quero saber dos cafes"
            },
            "messageType": "conversation",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].remote_jid == "5534999999999@s.whatsapp.net"
    assert msgs[0].type == "text"
    assert msgs[0].text == "oi, quero saber dos cafes"
    assert msgs[0].push_name == "Joao"


def test_parse_audio_message():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msg456"
            },
            "message": {
                "audioMessage": {
                    "url": "https://evo.com/audio/123",
                    "mimetype": "audio/ogg; codecs=opus"
                }
            },
            "messageType": "audioMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "audio"
    assert msgs[0].media_url == "https://evo.com/audio/123"


def test_parse_image_with_caption():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msg789"
            },
            "message": {
                "imageMessage": {
                    "url": "https://evo.com/img/456",
                    "mimetype": "image/jpeg",
                    "caption": "olha esse cafe"
                }
            },
            "messageType": "imageMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "image"
    assert msgs[0].text == "olha esse cafe"
    assert msgs[0].media_url == "https://evo.com/img/456"


def test_skip_from_me():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": True,
                "id": "msg999"
            },
            "message": {"conversation": "oi"},
            "messageType": "conversation",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert msgs == []


def test_skip_non_messages_upsert():
    payload = {
        "event": "connection.update",
        "instance": "test",
        "data": {"state": "open"}
    }

    msgs = parse_webhook_payload(payload)
    assert msgs == []


def test_parse_extended_text():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msgext"
            },
            "message": {
                "extendedTextMessage": {
                    "text": "mensagem com link https://example.com"
                }
            },
            "messageType": "extendedTextMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].text == "mensagem com link https://example.com"
