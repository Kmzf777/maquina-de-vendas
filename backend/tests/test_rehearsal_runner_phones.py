"""Testa a lógica de geração de telefones únicos por índice de arquétipo."""


def _phone_for_index(idx: int) -> str:
    return f"5511{(idx + 1):08d}"


def test_phone_index_zero():
    assert _phone_for_index(0) == "551100000001"


def test_phone_index_five():
    assert _phone_for_index(5) == "551100000006"


def test_phones_are_unique():
    phones = [_phone_for_index(i) for i in range(6)]
    assert len(set(phones)) == 6


def test_phones_are_strings():
    assert isinstance(_phone_for_index(0), str)
