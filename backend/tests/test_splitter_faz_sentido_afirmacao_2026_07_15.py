"""Afirmações de acolhimento não ganham "?" (auditoria QA valeria_inbound, 15/07/2026).

Origem: o roteiro usa aberturas "faz sentido ..." e "te interessa ..." em AFIRMAÇÕES de
acolhimento ("faz sentido querer alcançar todo mundo"). Elas batiam em _QUESTION_STARTERS e a
rede de segurança do "?" anexava "?" indevidamente, virando pergunta. A auditoria de 15/07
removeu esses dois starters ambíguos. O modelo já anexa "?" nas perguntas reais e
_ensure_question_mark retorna cedo quando a bolha já termina em "?" — perguntas legítimas
seguem intactas.
"""
from app.humanizer.splitter import split_into_bubbles, _ensure_question_mark


def test_faz_sentido_afirmacao_nao_ganha_interrogacao():
    """Afirmação de acolhimento aberta por 'faz sentido' → NÃO ganha '?'."""
    bubble = "faz sentido querer alcançar todo mundo"
    assert _ensure_question_mark(bubble) == bubble
    assert not _ensure_question_mark(bubble).endswith("?")


def test_te_interessa_afirmacao_nao_ganha_interrogacao():
    """Afirmação aberta por 'te interessa' → NÃO ganha '?'."""
    bubble = "te interessa conhecer o microlote"
    assert _ensure_question_mark(bubble) == bubble
    assert not _ensure_question_mark(bubble).endswith("?")


def test_pergunta_real_wh_ainda_ganha_interrogacao():
    """Regressão: pergunta interrogativa legítima ('qual ...') continua ganhando '?'."""
    assert _ensure_question_mark("qual volume você pensa em começar") == \
        "qual volume você pensa em começar?"


def test_faz_sentido_ja_pontuado_permanece_inalterado():
    """Se o modelo já emitiu 'faz sentido pra você?' → retorna igual, com exatamente um '?'."""
    bubble = "faz sentido pra você?"
    out = _ensure_question_mark(bubble)
    assert out == bubble
    assert out.endswith("?")
    assert not out.endswith("??")
