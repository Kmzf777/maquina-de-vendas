from types import SimpleNamespace as NS
from app.button_flow import valeria_tabela as t

ATACADO = [
 ("Canastra Canela — Moído 250g","R$ 28,70"),("Canastra Clássico — Em Grãos 1kg","R$ 97,70"),
 ("Canastra Clássico — Em Grãos 250g","R$ 31,70"),("Canastra Clássico — Em Grãos 500g","R$ 54,70"),
 ("Canastra Clássico — Moído 250g","R$ 28,70"),("Canastra Clássico — Moído 500g","R$ 52,70"),
 ("Canastra Suave — Em Grãos 1kg","R$ 97,70"),("Canastra Suave — Em Grãos 250g","R$ 31,70"),
 ("Canastra Suave — Em Grãos 500g","R$ 54,70"),("Canastra Suave — Moído 250g","R$ 28,70"),
 ("Canastra Suave — Moído 500g","R$ 52,70"),("Cápsula Canastra Canela — Display 10 cápsulas","R$ 22,90"),
 ("Cápsula Canastra Clássico — Display 10 cápsulas","R$ 22,90"),("Drip Coffee Canastra Suave — Display 10 sachês","R$ 24,90"),
 ("Granel Canastra Clássico — 2kg em grãos","R$ 169,70"),("Granel Canastra Suave — 2kg em grãos","R$ 169,70"),
 ("Granel Néctar de Minas Espresso — 2kg em grãos","R$ 166,70"),("Granel Néctar de Minas Intenso — 2kg em grãos","R$ 166,70"),
 ("Microlote — Em Grãos 250g","R$ 32,70"),("Microlote — Moído 250g","R$ 32,70"),
 ("Moedor + 10 pacotes granel","R$ 599,00"),("Moedor Elétrico Profissional — Unitário","R$ 949,00"),
 ("Néctar de Minas Blend Arábica+Robusta — Em Grãos 1kg","R$ 79,70"),("Néctar de Minas Gourmet — Em Grãos 1kg","R$ 88,70"),
 ("Néctar de Minas Gourmet — Kit 10un 500g","R$ 357,00"),("Néctar de Minas Gourmet — Moído 500g","R$ 39,70"),
]
PL = [("Café Canastra 250g — c/ embalagem Canastra","R$ 26,70","100 un"),("Café Canastra 250g — embalagem do cliente","R$ 25,70","100 un"),
      ("Café Canastra 500g — c/ embalagem Canastra","R$ 48,70","100 un"),("Café Canastra 500g — embalagem do cliente","R$ 47,70","100 un"),
      ("Microlote 250g — c/ embalagem Canastra","R$ 29,70","100 un"),("Microlote 250g — embalagem do cliente","R$ 27,70","50 un")]
def produtos():
    return ([{"sector":"Atacado","name":n,"price_formatted":p,"min_lot":None,"is_active":True} for n,p in ATACADO]
          + [{"sector":"Private Label","name":n,"price_formatted":p,"min_lot":m,"is_active":True} for n,p,m in PL])

def test_precos_filtra_setor_inativo_e_vazio():
    ps = produtos() + [{"sector":"Atacado","name":"X","price_formatted":"R$ 1,00","is_active":False,"min_lot":None},
                       {"sector":"Atacado","name":"Y","price_formatted":"","is_active":True,"min_lot":None}]
    p = t.precos_por_nome(ps, "Atacado")
    assert p["Canastra Clássico — Moído 250g"] == "R$ 28,70"
    assert "X" not in p and "Y" not in p and "Café Canastra 250g — embalagem do cliente" not in p

def test_card_resolve_precos_e_sai_dentro_do_limite():
    card = NS(id="classico", corpo="Clássico\n250g moído {preco:Canastra Clássico — Moído 250g}",
              skus=("Canastra Clássico — Moído 250g",), exige_min_lot=None)
    assert t.resolver_card(card, t.precos_por_nome(produtos(),"Atacado"), {}) == "Clássico\n250g moído R$ 28,70"

def test_card_some_se_sku_faltar():
    card = NS(id="x", corpo="{preco:Nao Existe}", skus=("Nao Existe",), exige_min_lot=None)
    assert t.resolver_card(card, t.precos_por_nome(produtos(),"Atacado"), {}) is None

def test_card_microlote_pl_some_enquanto_min_lot_for_50():
    card = NS(id="microlote", corpo="Microlote 250g {preco:Microlote 250g — c/ embalagem Canastra}",
              skus=("Microlote 250g — c/ embalagem Canastra","Microlote 250g — embalagem do cliente"), exige_min_lot="100 un")
    precos = t.precos_por_nome(produtos(), "Private Label"); lots = t.min_lots_por_nome(produtos(), "Private Label")
    assert t.resolver_card(card, precos, lots) is None   # "embalagem do cliente" ainda diz 50 un

def test_card_microlote_pl_sai_quando_todos_tem_100():
    ps = [dict(p, min_lot="100 un") if p["sector"] == "Private Label" else p for p in produtos()]
    card = NS(id="microlote", corpo="Microlote {preco:Microlote 250g — c/ embalagem Canastra}",
              skus=("Microlote 250g — c/ embalagem Canastra","Microlote 250g — embalagem do cliente"), exige_min_lot="100 un")
    assert t.resolver_card(card, t.precos_por_nome(ps, "Private Label"), t.min_lots_por_nome(ps, "Private Label")) == "Microlote R$ 29,70"

def test_card_acima_de_160_ou_3_quebras_some():
    precos = t.precos_por_nome(produtos(),"Atacado")
    assert t.resolver_card(NS(id="a", corpo="x"*161, skus=(), exige_min_lot=None), precos, {}) is None
    assert t.resolver_card(NS(id="a", corpo="a\nb\nc\nd", skus=(), exige_min_lot=None), precos, {}) is None

def test_tabela_atacado_tem_linhas_e_regras():
    txt = t.tabela_atacado(t.precos_por_nome(produtos(),"Atacado"), regras="✅ pedido mínimo R$500")
    assert "Clássico" in txt and "R$ 28,70" in txt and "R$ 97,70" in txt
    assert "Granel" in txt and "R$ 84,85/kg" in txt     # 169,70 / 2, derivado, nunca escrito à mão
    assert txt.rstrip().endswith("✅ pedido mínimo R$500")

def test_tabela_omite_linha_de_sku_inativo():
    ps = [p for p in produtos() if not p["name"].startswith("Moedor")]
    assert "Moedor" not in t.tabela_atacado(t.precos_por_nome(ps,"Atacado"), regras="")

def test_tabela_vazia_devolve_none():
    assert t.tabela_atacado({}, regras="x") is None

def test_total_pl_e_como_funciona():
    precos = t.precos_por_nome(produtos(), "Private Label")
    assert t.total_pl(precos) == "R$ 2.670,00"
    assert "R$ 2.670,00" in t.como_funciona_pl(precos, "exemplo: 100 pacotes = {total_pl} + fotolito")
    assert t.como_funciona_pl({}, "x {total_pl}") is None


import pytest

def _ps(nome, preco, setor="Atacado", lote=None):
    return {"sector": setor, "name": nome, "price_formatted": preco, "min_lot": lote, "is_active": True}

@pytest.mark.parametrize("ruim", ["R$ 28.70", "R$ 1.5", "R$ -5,00", "consulte 2 dias", "R$ 0,00",
                                  "sob consulta", "R$ 28,700", "28,70", "R$ 1.23,00"])
def test_preco_malformado_e_descartado(ruim):
    assert t.precos_por_nome([_ps("A", ruim)], "Atacado") == {}

def test_preco_nao_string_e_ignorado():
    ps = [_ps("A", 28.7), _ps("B", None), _ps("C", "R$ 1,00", lote=50), _ps("D", "R$ 2,00", lote="100 un")]
    assert t.precos_por_nome(ps, "Atacado") == {"C": "R$ 1,00", "D": "R$ 2,00"}
    assert t.min_lots_por_nome(ps, "Atacado") == {"D": "100 un"}

def test_milhar_parse_e_formato():
    assert t.precos_por_nome([_ps("A", "R$ 1.234,50"), _ps("B", "R$ 949,00"), _ps("C", "R$ 949")], "Atacado") == {
        "A": "R$ 1.234,50", "B": "R$ 949,00", "C": "R$ 949"}
    assert t.total_pl({t.SKU_BASE_PL: "R$ 1.234,50"}) == "R$ 123.450,00"
    assert t.total_pl({t.SKU_BASE_PL: "R$ 26,705"}) is None

def test_arredondamento_half_up_no_por_kg():
    p = {"Granel Canastra Clássico — 2kg em grãos": "R$ 169,70", "Granel Canastra Suave — 2kg em grãos": "R$ 169,70"}
    assert "R$ 84,85/kg" in t.tabela_atacado(p, "")
    p = {"Granel Canastra Clássico — 2kg em grãos": "R$ 100,01"}
    assert "R$ 50,01/kg" in t.tabela_atacado(p, "")   # 50,005 -> 50,01

def _atacado(**troca):
    d = dict(ATACADO); d.update(troca)
    return t.precos_por_nome([_ps(n, p) for n, p in d.items()], "Atacado")

def test_classico_diferente_de_suave():
    txt = t.tabela_atacado(_atacado(**{"Canastra Suave — Moído 250g": "R$ 29,70"}), "")
    assert "250g  moído Clássico R$ 28,70 · Suave R$ 29,70 · grão R$ 31,70" in txt

def test_microlote_moido_diferente_de_grao():
    txt = t.tabela_atacado(_atacado(**{"Microlote — Em Grãos 250g": "R$ 33,70"}), "")
    assert "☕ Microlote  250g moído R$ 32,70 · grão R$ 33,70" in txt

def test_granel_diferente_e_unico():
    txt = t.tabela_atacado(_atacado(**{"Granel Canastra Suave — 2kg em grãos": "R$ 171,70"}), "")
    assert "Clássico R$ 169,70 (R$ 84,85/kg) · Suave R$ 171,70 (R$ 85,85/kg)" in txt
    p = _atacado(); del p["Granel Canastra Suave — 2kg em grãos"]
    assert "Clássico R$ 169,70 (R$ 84,85/kg)" in t.tabela_atacado(p, "") and "Clássico/Suave" not in t.tabela_atacado(p, "")
    p = _atacado(); del p["Granel Canastra Clássico — 2kg em grãos"]
    assert "Suave R$ 169,70 (R$ 84,85/kg)" in t.tabela_atacado(p, "") and "Clássico/Suave" not in t.tabela_atacado(p, "")

def test_capsulas_diferentes_imprime_ambas():
    txt = t.tabela_atacado(_atacado(**{"Cápsula Canastra Canela — Display 10 cápsulas": "R$ 23,90"}), "")
    assert "Cápsulas (10 un) Clássico R$ 22,90 · Canela R$ 23,90" in txt

def test_exige_min_lot_sem_o_sku_em_min_lots_some():
    card = NS(id="x", corpo="{preco:A}", skus=("A",), exige_min_lot="100 un")
    assert t.resolver_card(card, {"A": "R$ 1,00"}, {}) is None

def test_layout_completo_da_tabela_atacado():
    txt = t.tabela_atacado(t.precos_por_nome(produtos(), "Atacado"), regras="REGRAS")
    assert txt == (
        "tabela atacado — preço por pacote 📋\n\n"
        "☕ Clássico · Suave\n"
        "250g  moído R$ 28,70 · grão R$ 31,70\n"
        "500g  moído R$ 52,70 · grão R$ 54,70\n"
        "1kg   grão R$ 97,70\n"
        "☕ Canela  250g moído R$ 28,70\n"
        "☕ Microlote  250g R$ 32,70\n"
        "☕ Néctar de Minas  Gourmet 1kg R$ 88,70 · moído 500g R$ 39,70 · Blend 1kg R$ 79,70\n"
        "📦 Granel 2kg em grão  Clássico/Suave R$ 169,70 (R$ 84,85/kg) · Néctar R$ 166,70\n"
        "☕ Cápsulas (10 un) R$ 22,90 · Drip (10 sachês) R$ 24,90\n"
        "⚙️ Moedor profissional R$ 949,00 · Moedor + 10 granel R$ 599,00\n\n"
        "REGRAS")
