# backend/tests/test_meta_quoted_messages.py
from app.webhook.meta_parser import parse_meta_webhook_payload
from app.webhook.parser import IncomingMessage


def _make_meta_payload(msg_dict: dict, from_number: str = "5511999999999") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5500000000000",
                        "phone_number_id": "999"
                    },
                    "contacts": [{"profile": {"name": "Test"}}],
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.reply1",
                        "timestamp": "1716900000",
                        **msg_dict,
                    }]
                }
            }]
        }]
    }


def test_parse_text_reply_with_context():
    """Text message quoting another message should populate quoted_wamid."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "sim, esse mesmo"},
        "context": {"id": "wamid.original1"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].text == "sim, esse mesmo"
    assert msgs[0].quoted_wamid == "wamid.original1"
    assert msgs[0].message_id == "wamid.reply1"


def test_parse_text_without_context():
    """Text message without context should have quoted_wamid = None."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "olá"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].quoted_wamid is None


def test_parse_image_reply_with_context():
    """Image message quoting another should populate quoted_wamid."""
    payload = _make_meta_payload({
        "type": "image",
        "image": {"id": "media123", "mime_type": "image/jpeg"},
        "context": {"id": "wamid.original2"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "image"
    assert msgs[0].quoted_wamid == "wamid.original2"
