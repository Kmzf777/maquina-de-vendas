import pytest
from app.leads.service import _normalize_phone


@pytest.mark.parametrize("raw,expected", [
    ("+5511999990000", "5511999990000"),
    ("5511999990000", "5511999990000"),
    ("+55 11 99999-0000", "5511999990000"),
    ("(11) 99999-0000", "11999990000"),     # sem DDI — aceita como está, sem inventar 55
    ("whatsapp:+5511999990000", "5511999990000"),
    ("whatsapp:5511999990000", "5511999990000"),
    (" +55 11 9 9999 0000 ", "5511999990000"),
    ("", ""),
    (None, ""),
])
def test_normalize_phone(raw, expected):
    assert _normalize_phone(raw) == expected
