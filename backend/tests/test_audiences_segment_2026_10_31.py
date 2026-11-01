"""Cartão 4e0494e0: janela de 365 dias, regra PL/Atacado, montagem da pessoa e diff."""
from datetime import datetime, timedelta, timezone

import pytest

from app.audiences.diff import diff_identificadores, ident_hash
from app.audiences.segment import classificar, dentro_da_janela, montar_pessoa
from app.audiences.types import Detalhe, Fatos

AGORA = datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc)
CPF = "12345678901"
CNPJ = "12345678000199"


def fatos(**kw) -> Fatos:
    base = dict(
        lead_id="L1",
        ultima_compra=AGORA - timedelta(days=10),
        receita_365=1234.567,
        nome="João da Silva",
        lead_phone=None,
        lead_email=None,
    )
    base.update(kw)
    return Fatos(**base)


# janela

def test_janela_364_dias_entra():
    assert dentro_da_janela(fatos(ultima_compra=AGORA - timedelta(days=364)), AGORA)


def test_janela_366_dias_sai():
    assert not dentro_da_janela(fatos(ultima_compra=AGORA - timedelta(days=366)), AGORA)


def test_janela_exatamente_365_entra():
    assert dentro_da_janela(fatos(ultima_compra=AGORA - timedelta(days=365)), AGORA)


# segmento

@pytest.mark.parametrize("kw", [
    {"pipeline_pl": True},
    {"tag_pl": True},
    {"fotolito": True},
    {"produto_pl": True},
    {"segmento": "private_label"},
])
def test_criterio_pl(kw):
    assert classificar(fatos(**kw)) == (True, False)


@pytest.mark.parametrize("kw", [
    {"pipeline_atacado": True},
    {"tag_atacado": True},
    {"segmento": "atacado"},
])
def test_criterio_atacado(kw):
    assert classificar(fatos(**kw)) == (False, True)


def test_cnpj_sem_classe_vira_atacado():
    assert classificar(fatos(docs=[CNPJ])) == (False, True)


def test_cpf_sem_classe_fica_fora():
    f = fatos(docs=[CPF], lead_phone="34991234567")
    assert classificar(f) == (False, False)
    assert montar_pessoa(f, {}) is None


def test_pl_e_atacado_os_dois():
    assert classificar(fatos(tag_pl=True, pipeline_atacado=True)) == (True, True)


def test_pl_com_cnpj_fica_so_pl():
    assert classificar(fatos(produto_pl=True, docs=[CNPJ])) == (True, False)


# pessoa

def test_fixo_e_bling_nao_entram():
    f = fatos(tag_pl=True, lead_phone="bling-123", fones_bling=["553432321000", "5534991234567"])
    p = montar_pessoa(f, {})
    assert p.celulares == ["5534991234567"]


def test_celular_duplicado_aparece_uma_vez():
    f = fatos(tag_pl=True, lead_phone="(34) 99123-4567", fones_bling=["5534991234567", "553491234567"])
    assert montar_pessoa(f, {}).celulares == ["5534991234567"]


def test_email_do_detalhe_entra():
    f = fatos(
        tag_pl=True,
        lead_email=" Joao@Ex.com ",
        emails_bling=["joao@ex.com"],
        contatos_bling=[("canastra", 7)],
    )
    p = montar_pessoa(f, {("canastra", 7): Detalhe(email="Compras@Loja.com.br")})
    assert p.emails == ["joao@ex.com", "compras@loja.com.br"]


def test_endereco_vem_do_detalhe():
    f = fatos(pipeline_atacado=True, contatos_bling=[("a", 1), ("b", 2)])
    detalhes = {
        ("a", 1): Detalhe(municipio="Belo Horizonte", uf="MG"),  # sem CEP, pula
        ("b", 2): Detalhe(municipio="São Roque de Minas", uf="mg", cep="37928-000"),
    }
    p = montar_pessoa(f, detalhes)
    assert (p.cidade, p.uf, p.cep) == ("saoroquedeminas", "mg", "37928000")
    assert (p.nome, p.sobrenome) == ("joao", "silva")
    assert p.valor == 1234.57
    assert (p.pl, p.atacado) == (False, True)


def test_segmento_none_nao_quebra():
    f = fatos(segmento=None, docs=[CNPJ])
    p = montar_pessoa(f, {})
    assert p is not None and p.atacado and not p.pl
    assert (p.cidade, p.uf, p.cep) == (None, None, None)


# diff

def test_diff():
    assert diff_identificadores({"a", "b"}, {"b", "c"}) == ({"c"}, {"a"})


def test_ident_hash_estavel_na_ordem_das_chaves():
    assert ident_hash({"a": 1, "b": "x"}) == ident_hash({"b": "x", "a": 1})
    assert len(ident_hash({"a": 1})) == 64
