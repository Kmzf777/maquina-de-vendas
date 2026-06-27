"""Rede de segurança do '?' (caso Rubens): perguntas inequívocas recebem '?' determinístico."""
from app.humanizer.splitter import split_into_bubbles, _ensure_question_mark


def test_readiciona_interrogacao_em_pergunta_wh():
    assert _ensure_question_mark("quer que eu te passe os detalhes") == "quer que eu te passe os detalhes?"
    assert _ensure_question_mark("qual desses formatos faz mais sentido pro seu negocio") == \
        "qual desses formatos faz mais sentido pro seu negocio?"
    assert _ensure_question_mark("o que te fez querer entrar nesse mercado") == \
        "o que te fez querer entrar nesse mercado?"


def test_nao_mexe_em_declarativa_ou_ja_pontuada():
    # declarativa sem starter interrogativo → não vira pergunta
    assert _ensure_question_mark("a gente entrega em BH") == "a gente entrega em BH"
    # já tem '?' → inalterada
    assert _ensure_question_mark("qual o volume?") == "qual o volume?"
    # reticências (pausa) → não mexe
    assert _ensure_question_mark("deixa eu ver aqui...") == "deixa eu ver aqui..."
    # termina com '!' → não mexe
    assert _ensure_question_mark("que massa!") == "que massa!"


def test_split_into_bubbles_aplica_interrogacao():
    out = split_into_bubbles("qual desses faz mais sentido pro seu negocio")
    assert out == ["qual desses faz mais sentido pro seu negocio?"]
