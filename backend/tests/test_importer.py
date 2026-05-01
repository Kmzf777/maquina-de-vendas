from app.campaign.importer import normalize_phone, parse_csv


def test_normalize_full_number():
    assert normalize_phone("5534999999999") == "5534999999999"


def test_normalize_without_country():
    assert normalize_phone("34999999999") == "5534999999999"


def test_normalize_with_plus():
    assert normalize_phone("+5534999999999") == "5534999999999"


def test_normalize_with_formatting():
    assert normalize_phone("(34) 99999-9999") == "5534999999999"


def test_normalize_landline():
    # 10 dígitos (sem DDI) → add 55 → 12 dígitos → injeta 9 (contexto WhatsApp = mobile only)
    assert normalize_phone("3432221111") == "5534932221111"


def test_normalize_old_mobile_12digits():
    # CSV com número no formato antigo (12 dígitos com DDI) → injeta 9
    assert normalize_phone("553898422923") == "5538998422923"


def test_normalize_invalid():
    assert normalize_phone("123") is None
    assert normalize_phone("abcdefghij") is None


def test_parse_csv_basic():
    csv_content = "telefone\n5534999999999\n5534888888888\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 2
    assert result.valid[0] == "5534999999999"


def test_parse_csv_normalizes_old_format():
    # CSV com número antigo (12 dígitos) → deve sair normalizado (13 dígitos)
    csv_content = "telefone\n553898422923\n"
    result = parse_csv(csv_content)
    assert result.valid[0] == "5538998422923"


def test_parse_csv_with_invalid():
    csv_content = "phone\n5534999999999\n123\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 1
    assert len(result.invalid) == 1
