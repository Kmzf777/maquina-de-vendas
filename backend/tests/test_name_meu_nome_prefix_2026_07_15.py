"""Higiene de nome: prefixo de APRESENTAÇÃO ("meu nome é X") — auditoria 15/07.

Caso real ("olá meu"): um lead gravado com a frase inteira "meu nome é Ricardo" no
campo nome produziu a saudação de broadcast "olá meu", porque `sanitize_display_name`
não removia o prefixo de apresentação e o `_lead_first_name` do worker faz
`sanitize_display_name(...).split()[0]` -> "meu".

Frente B: o strip de apresentação foi integrado ao `strip_greeting_prefix` (base
compartilhada por `sanitize_display_name`, broadcast/worker e follow-up/LP), no mesmo
laço iterativo que já remove saudações. Após remover o prefixo, o restante segue pelas
checagens normais (conversacional/apelido/negócio), então "meu nome é sim" -> "sim" ->
None.
"""
import pytest

from app.leads.service import strip_greeting_prefix, sanitize_display_name
from app.broadcast.worker import _lead_first_name


# ─── sanitize_display_name: remove prefixo de apresentação ───────────────────

@pytest.mark.parametrize("raw,expected", [
    ("meu nome é Ricardo", "Ricardo"),
    ("Meu nome é Ricardo", "Ricardo"),
    ("MEU NOME É RICARDO", "RICARDO"),      # preserva a caixa do restante
    ("meu nome eh Ricardo", "Ricardo"),
    ("meu nome e Ricardo", "Ricardo"),      # sem acento
    ("meu nome Ricardo", "Ricardo"),        # sem verbo
    ("Me chamo Ana Paula", "Ana Paula"),
    ("chamo-me Ana", "Ana"),
    ("sou o Carlos", "Carlos"),
    ("sou a Marina", "Marina"),
    ("eu sou o Carlos", "Carlos"),
    ("eu sou Carlos", "Carlos"),
    ("aqui é o João", "João"),
    ("aqui é a Julia", "Julia"),
    ("pode me chamar de Dé", "Dé"),
    ("pode chamar de Zé", "Zé"),
    # Saudação + apresentação combinadas (mesmo laço iterativo)
    ("Olá, meu nome é Ricardo", "Ricardo"),
    ("Boa tarde, me chamo Ana Paula", "Ana Paula"),
])
def test_sanitize_display_name_remove_prefixo_apresentacao(raw, expected):
    assert sanitize_display_name(raw) == expected


def test_sanitize_display_name_apresentacao_com_resto_conversacional_vira_none():
    """Após remover "meu nome é", o restante "sim" cai em _CONVERSATIONAL_NON_NAMES."""
    assert sanitize_display_name("meu nome é sim") is None
    assert sanitize_display_name("meu nome é ok") is None


@pytest.mark.parametrize("raw", [
    # Nomes reais que apenas COMEÇAM parecido com um prefixo de apresentação — jamais
    # truncar (a fronteira \s+ de cada alternativa protege estes).
    "Souza Lima",
    "Eduardo",
    "Meurer",
    "Aquiles",
])
def test_sanitize_display_name_nao_trunca_nome_parecido_com_apresentacao(raw):
    assert sanitize_display_name(raw) == raw


# ─── strip_greeting_prefix: regressão dos casos documentados ─────────────────

def test_strip_greeting_prefix_regressao_saudacao():
    """Guardas de regressão: o strip de apresentação não pode quebrar os casos de
    saudação já cobertos pela Task C-4."""
    assert strip_greeting_prefix("Boa tarde.... Luiz") == "Luiz"
    assert strip_greeting_prefix("Olá, boa tarde") is None
    assert strip_greeting_prefix("Maycon") == "Maycon"


def test_strip_greeting_prefix_apresentacao():
    assert strip_greeting_prefix("meu nome é Ricardo") == "Ricardo"
    assert strip_greeting_prefix("meu nome é sim") == "sim"   # o restante ainda é validado por sanitize_display_name


# ─── broadcast: _lead_first_name deriva "Ricardo", não "meu" ─────────────────

def test_lead_first_name_prefixo_apresentacao():
    assert _lead_first_name({"name": "meu nome é Ricardo"}) == "Ricardo"


def test_lead_first_name_sem_nome_usavel_cai_no_fallback():
    assert _lead_first_name({"name": "meu nome é sim"}) == "você"
    assert _lead_first_name({"name": ""}) == "você"
    assert _lead_first_name({}) == "você"
