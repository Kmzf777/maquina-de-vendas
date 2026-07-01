from app.webhook.parser import IncomingMessage, webhook_identity


def _msg(**kw):
    base = dict(from_number="", remote_jid="", message_id="w1", timestamp="1", type="text")
    base.update(kw)
    return IncomingMessage(**base)


def test_webhook_identity_prefers_phone():
    m = _msg(from_number="5534999999999", bsuid="US.123")
    assert webhook_identity(m) == "5534999999999"


def test_webhook_identity_falls_back_to_bsuid():
    m = _msg(from_number="", bsuid="US.13491208655302741918")
    assert webhook_identity(m) == "US.13491208655302741918"


def test_incoming_message_has_bsuid_and_username_fields():
    m = _msg(bsuid="US.123", username="pablomorales")
    assert m.bsuid == "US.123"
    assert m.username == "pablomorales"
