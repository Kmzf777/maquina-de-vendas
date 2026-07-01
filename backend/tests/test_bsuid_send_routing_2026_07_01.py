from app.whatsapp.meta import _recipient_field


def test_recipient_field_phone_uses_to():
    assert _recipient_field("5534999999999") == {"to": "5534999999999"}


def test_recipient_field_bsuid_uses_recipient():
    assert _recipient_field("US.13491208655302741918") == {"recipient": "US.13491208655302741918"}


def test_recipient_field_parent_bsuid_uses_recipient():
    assert _recipient_field("US.ENT.11815799212886844830") == {"recipient": "US.ENT.11815799212886844830"}
