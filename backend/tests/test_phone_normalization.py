import pytest
from app.leads.service import normalize_phone


@pytest.mark.parametrize("raw,expected", [
    # casos existentes (comportamento inalterado)
    ("+5511999990000", "5511999990000"),
    ("5511999990000", "5511999990000"),
    ("+55 11 99999-0000", "5511999990000"),
    ("(11) 99999-0000", "11999990000"),       # sem DDI — aceita como está
    ("whatsapp:+5511999990000", "5511999990000"),
    ("whatsapp:5511999990000", "5511999990000"),
    (" +55 11 9 9999 0000 ", "5511999990000"),
    ("", ""),
    (None, ""),
    # casos do 9º dígito
    ("553898422923", "5538998422923"),          # 12 dígitos BR → injeta 9
    ("+553898422923", "5538998422923"),          # + prefix + 12 dígitos → injeta 9
    ("5538998422923", "5538998422923"),          # já 13 dígitos → inalterado
    ("whatsapp:553898422923", "5538998422923"),  # whatsapp prefix + 12 dígitos
    ("551299990000", "5512999990000"),           # DDD 12 (SP interior) sem 9
    ("5521912345678", "5521912345678"),          # 13 dígitos RJ → inalterado
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
