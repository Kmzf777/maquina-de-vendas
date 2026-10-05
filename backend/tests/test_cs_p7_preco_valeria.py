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
