"""P7 — preço na ValerIA de botões (call de 01/10).

`{classico, 250g}` casa com DOIS SKUs ativos do atacado (Moído R$ 28,70 e Em
Grãos R$ 31,70) e o `preco_do_no` cortava a linha de preço com 2 candidatos: o
N5/N5b saíam sem preço nenhum. Decisão do dono (06/10): mostrar o MENOR preço com
"a partir de" quando os candidatos são o mesmo café em formatos diferentes.
Produtos-base diferentes continuam cortando a linha — essa é a regra Ritz.

O catálogo abaixo é cópia literal das linhas de `products` de produção
(sector "Atacado", is_active) lidas em 06/10/2026.
"""
import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner


def _sku(nome, preco, setor="Atacado"):
    return {"sector": setor, "name": nome, "price_formatted": preco,
            "min_lot": None, "description": "", "image_urls": []}


CATALOGO = [
    _sku("Canastra Canela — Moído 250g", "R$ 28,70"),
    _sku("Canastra Clássico — Em Grãos 1kg", "R$ 97,70"),
    _sku("Canastra Clássico — Em Grãos 250g", "R$ 31,70"),
    _sku("Canastra Clássico — Em Grãos 500g", "R$ 54,70"),
    _sku("Canastra Clássico — Moído 250g", "R$ 28,70"),
    _sku("Canastra Clássico — Moído 500g", "R$ 52,70"),
    _sku("Canastra Suave — Em Grãos 250g", "R$ 31,70"),
    _sku("Canastra Suave — Moído 250g", "R$ 28,70"),
    _sku("Granel Canastra Clássico — 2kg em grãos", "R$ 169,70"),
    _sku("Granel Canastra Suave — 2kg em grãos", "R$ 169,70"),
    _sku("Microlote — Em Grãos 250g", "R$ 32,70"),
    _sku("Microlote — Moído 250g", "R$ 32,70"),
    # Mesmo nome em OUTRO setor e outro preço: o filtro de setor tem de valer.
    _sku("Canastra Clássico — Moído 250g", "R$ 39,90", setor="Varejo"),
]


@pytest.fixture
def catalogo():
    """Troca o catálogo do Supabase por uma lista fixa (o import é tardio)."""
    def _com(produtos):
        return patch("app.agent.catalog._fetch_active_products",
                     MagicMock(return_value=produtos))
    return _com


# ── preco_do_no ─────────────────────────────────────────────────────────────
def test_n5_classico_com_dois_formatos_mostra_a_partir_do_menor(catalogo):
    with catalogo(CATALOGO):
        assert runner.preco_do_no(reg.NOS["N5"]) == "a partir de R$ 28,70"


def test_n5b_suave_com_dois_formatos_mostra_a_partir_do_menor(catalogo):
    with catalogo(CATALOGO):
        assert runner.preco_do_no(reg.NOS["N5b"]) == "a partir de R$ 28,70"


def test_menor_preco_independe_da_ordem_do_catalogo(catalogo):
    with catalogo(list(reversed(CATALOGO))):
        assert runner.preco_do_no(reg.NOS["N5"]) == "a partir de R$ 28,70"


def test_candidato_unico_sai_sem_prefixo(catalogo):
    so_moido = [p for p in CATALOGO if p["name"] != "Canastra Clássico — Em Grãos 250g"]
    with catalogo(so_moido):
        assert runner.preco_do_no(reg.NOS["N5"]) == "R$ 28,70"


def test_produtos_base_diferentes_cortam_a_linha(catalogo):
    """"Moído 250g" casa Canela, Clássico, Suave e Microlote: cafés DIFERENTES.

    Cotar o menor deles seria cotar um café pelo preço de outro — a classe do
    incidente Ritz (drip cotado misturando com Microlote).
    """
    no = dataclasses.replace(reg.NOS["N5"], produto="Moído 250g")
    with catalogo(CATALOGO):
        assert runner.preco_do_no(no) == ""


def test_preco_ilegivel_corta_a_linha(catalogo):
    quebrado = [_sku("Canastra Clássico — Moído 250g", ""),
                _sku("Canastra Clássico — Em Grãos 250g", "R$ 31,70")]
    with catalogo(quebrado):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""


def test_nenhum_candidato_continua_sem_preco(catalogo):
    with catalogo([_sku("Microlote — Moído 250g", "R$ 32,70")]):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""


# ── produto-base ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("nome", [
    "Canastra Clássico — Moído 250g",
    "Canastra Clássico — Em Grãos 250g",
    "Canastra Classico - em graos 250g",
    "CANASTRA CLÁSSICO GRÃOS 250G",
])
def test_produto_base_ignora_formato_acento_e_pontuacao(nome):
    assert runner._produto_base(nome) == "canastra classico 250g"


def test_produto_base_distingue_cafes_diferentes():
    assert (runner._produto_base("Canastra Clássico — Moído 250g")
            != runner._produto_base("Canastra Suave — Moído 250g"))


# ── o corpo que o lead lê ───────────────────────────────────────────────────
class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(body)
        return {"messages": [{"id": "wamid.1"}]}


@pytest.fixture
def sem_foto(monkeypatch):
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("no_id", ["N5", "N5b"])
async def test_corpo_com_faixa_nao_empilha_qualificador(no_id, catalogo, sem_foto):
    with catalogo(CATALOGO):
        contexto = {"preco": runner.preco_do_no(reg.NOS[no_id])}
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS[no_id], contexto)
    corpo = p.chamadas[0]
    assert "a partir de R$ 28,70 a unidade no atacado." in corpo
    assert "gira em torno de a partir de" not in corpo
    assert "{preco}" not in corpo
    assert "gostaria de ser encaminhado ao vendedor?" in corpo


@pytest.mark.asyncio
async def test_preco_unico_mantem_o_qualificador(sem_foto):
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {"preco": "R$ 28,70"})
    assert "gira em torno de R$ 28,70 a unidade no atacado." in p.chamadas[0]


@pytest.mark.parametrize("qualificador", [
    "gira em torno de", "fica por volta de", "na faixa de", "por volta de",
])
def test_qualquer_qualificador_aprovado_sai_antes_da_faixa(qualificador):
    corpo = f"{qualificador} {{preco}} a unidade."
    texto = runner._resolver(corpo, {"preco": "a partir de R$ 28,70"})
    assert texto == "a partir de R$ 28,70 a unidade."


def test_qualificador_longe_do_marcador_fica():
    """Só sai o qualificador COLADO no {preco}; o resto do texto é do editor."""
    corpo = "o preço gira em torno de mercado.\nvalor: {preco}."
    texto = runner._resolver(corpo, {"preco": "a partir de R$ 28,70"})
    assert texto == "o preço gira em torno de mercado.\nvalor: a partir de R$ 28,70."


# ── revisão de 06/10 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("corpo,esperado", [
    ("Gira em torno de {preco} a unidade.", "A partir de R$ 28,70 a unidade."),
    ("Esse é o Clássico.\nFica por volta de {preco}.", "Esse é o Clássico.\nA partir de R$ 28,70."),
    ("Bom café. Na faixa de {preco} a unidade.", "Bom café. A partir de R$ 28,70 a unidade."),
])
def test_qualificador_maiusculo_no_inicio_da_frase_capitaliza_a_faixa(corpo, esperado):
    """O editor marcou o início da frase com maiúscula; tirar o qualificador não pode
    deixar a frase começando em minúscula."""
    assert runner._resolver(corpo, {"preco": "a partir de R$ 28,70"}) == esperado


def test_qualificador_minusculo_mantem_a_faixa_minuscula():
    """O registry escreve tudo em minúscula de propósito (tom de WhatsApp): não inventa
    maiúscula onde o editor não pôs."""
    corpo = "esse é o Clássico.\n\ngira em torno de {preco} a unidade."
    assert runner._resolver(corpo, {"preco": "a partir de R$ 28,70"}) == (
        "esse é o Clássico.\n\na partir de R$ 28,70 a unidade.")


@pytest.mark.parametrize("precos", [
    (28.7, 31.7),
    (28.7, "R$ 31,70"),
    (None, 31.7),
])
def test_preco_numerico_entre_os_formatos_corta_a_linha(catalogo, precos):
    """price_formatted numérico (float vindo do banco/planilha) levantava AttributeError
    no parse_brl — fora do except ValueError, derrubando o envio do nó."""
    quebrado = [_sku("Canastra Clássico — Moído 250g", precos[0]),
                _sku("Canastra Clássico — Em Grãos 250g", precos[1])]
    with catalogo(quebrado):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""


def test_preco_numerico_em_candidato_unico_corta_a_linha(catalogo):
    with catalogo([_sku("Canastra Clássico — Moído 250g", 28.7)]):
        assert runner.preco_do_no(reg.NOS["N5"]) == ""
