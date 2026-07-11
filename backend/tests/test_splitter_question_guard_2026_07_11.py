"""Guardas na rede de segurança do '?' (Trilha B, 2026-07-11).

Origem: lead 5561999119005 (Fabi, conv befd097d, 11/07). A abertura de private
label despejou 4 parágrafos; o clamp de overflow (MAX_BUBBLES=3) fundiu os
parágrafos 3+4 numa única bolha de 286 chars com "\n\n" interno. Essa bolha
COMEÇA com uma frase clivada declarativa ("o que está incluso é...") — que bate
em _QUESTION_STARTERS — e TERMINA sem pontuação (frase de fechamento). A rede
do "?" viu "starter interrogativo + sem pontuação" e anexou "?" indevidamente
ao fim de uma afirmação.

Duas guardas conservadoras em _ensure_question_mark:
1. Bolha com "\n\n" interno (fundida pelo clamp) → nunca anexa "?".
2. Bolha com mais de 120 chars → nunca anexa "?" (a classe de falha original,
   caso 5531999844461, é uma pergunta curta que perdeu o "?").
"""
from app.humanizer.splitter import split_into_bubbles, _ensure_question_mark


FABI_BUBBLE = (
    "o que está incluso é o design da embalagem com a sua marca, a produção da "
    "embalagem, a torra do café que é cultivado nas nossas fazendas, a moagem, "
    "empacotamento, selagem, datação, separação e o envio dos produtos\n\n"
    "os cafés chegam prontos pra você comercializar com a sua marca própria"
)


def test_caso_fabi_bolha_fundida_nao_ganha_interrogacao():
    """Regressão: bolha fundida por overflow, starter 'o que', sem pontuação final → NÃO ganha '?'."""
    assert _ensure_question_mark(FABI_BUBBLE) == FABI_BUBBLE


def test_bolha_curta_nao_fundida_preserva_comportamento_original():
    """Fix original preservado: pergunta curta, starter, sem pontuação → ganha '?'."""
    bubble = "qual desses te chamou mais atenção"
    assert _ensure_question_mark(bubble) == bubble + "?"


def test_limite_120_chars_ganha_interrogacao():
    """Bolha de exatamente 120 chars, com starter e sem pontuação → ganha '?'."""
    starter = "qual "
    filler = "a" * (120 - len(starter))
    bubble = starter + filler
    assert len(bubble) == 120
    assert _ensure_question_mark(bubble) == bubble + "?"


def test_limite_121_chars_nao_ganha_interrogacao():
    """Bolha de 121 chars (1 a mais que o limite) → NÃO ganha '?', mesmo com starter."""
    starter = "qual "
    filler = "a" * (121 - len(starter))
    bubble = starter + filler
    assert len(bubble) == 121
    assert _ensure_question_mark(bubble) == bubble


def test_bolha_curta_com_paragrafo_interno_nao_ganha_interrogacao():
    """Bolha CURTA mas com '\\n\\n' interno (fundida) + starter → NÃO ganha '?'."""
    bubble = "qual desses\n\nte chamou mais atencao"
    assert _ensure_question_mark(bubble) == bubble


def test_split_into_bubbles_caso_fabi_fim_a_fim():
    """4 parágrafos reproduzindo o turno da Fabi → clamp a 3 bolhas; a 3ª NÃO termina em '?'."""
    p1 = "oi Fabi, tudo bem? aqui é a valéria da café canastra"
    p2 = "a gente faz café de marca própria pra quem quer vender com a sua marca"
    p3 = (
        "o que está incluso é o design da embalagem com a sua marca, a produção da "
        "embalagem, a torra do café que é cultivado nas nossas fazendas, a moagem, "
        "empacotamento, selagem, datação, separação e o envio dos produtos"
    )
    p4 = "os cafés chegam prontos pra você comercializar com a sua marca própria"
    text = "\n\n".join([p1, p2, p3, p4])

    bubbles = split_into_bubbles(text)

    assert len(bubbles) == 3
    assert not bubbles[2].endswith("?"), f"3a bolha nao deveria ganhar '?': {bubbles[2]!r}"
