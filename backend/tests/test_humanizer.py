from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay


def test_split_basic():
    text = "oi, tudo bem?\n\naqui e a valeria, da cafe canastra\n\nvoce trabalha com revenda?"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    assert bubbles[0] == "oi, tudo bem?"
    assert bubbles[2] == "voce trabalha com revenda?"


def test_split_strips_whitespace():
    text = "  msg1  \n\n  msg2  \n\n"
    bubbles = split_into_bubbles(text)
    assert bubbles == ["msg1", "msg2"]


def test_split_single_message():
    text = "uma mensagem so"
    bubbles = split_into_bubbles(text)
    assert bubbles == ["uma mensagem so"]


def test_split_empty():
    assert split_into_bubbles("") == []
    assert split_into_bubbles("\n\n\n\n") == []


def test_typing_delay_range():
    delay = calculate_typing_delay("oi")
    assert 0.3 < delay < 2.0

    delay = calculate_typing_delay("a" * 200)
    assert delay <= 12.0


def test_typing_delay_capped():
    delay = calculate_typing_delay("a" * 1000)
    assert delay <= 12.0


def test_split_fixes_lowercase_reais():
    text = "o 250g sai r$23,90 a unidade\n\no pedido minimo e de 100"
    bubbles = split_into_bubbles(text)
    assert bubbles[0] == "o 250g sai R$23,90 a unidade"
    assert bubbles[1] == "o pedido minimo e de 100"


def test_split_preserves_uppercase_reais():
    text = "o valor e R$44,90"
    bubbles = split_into_bubbles(text)
    assert bubbles[0] == "o valor e R$44,90"
