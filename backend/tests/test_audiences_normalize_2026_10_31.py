"""Cartão 4e0494e0: normalização dos identificadores dos públicos PL/Atacado."""
import hashlib
from datetime import datetime, timezone

from app.audiences import normalize as n
from app.audiences.types import AUDIENCES, Fatos


def test_celular_com_mascara():
    assert n.celular_br("+55 (34) 99123-4567") == "5534991234567"


def test_celular_antigo_ganha_9():
    assert n.celular_br("553491234567") == "5534991234567"


def test_fixo_fica_fora():
    assert n.celular_br("553432321000") is None
    assert n.celular_br("(34) 3232-1000") is None


def test_marcador_bling_e_vazio_ficam_fora():
    assert n.celular_br("bling-55") is None
    assert n.celular_br(None) is None


def test_email():
    assert n.email(" Fulano@Gmail.COM ") == "fulano@gmail.com"
    assert n.email("semarroba") is None
    assert n.email("@x.com") is None
    assert n.email(None) is None


def test_nome_sobrenome():
    assert n.nome_sobrenome("José da Silva-Júnior.") == ("jose", "silvajunior")
    assert n.nome_sobrenome("Ana") == ("ana", None)
    assert n.nome_sobrenome("  ") == (None, None)
    assert n.nome_sobrenome(None) == (None, None)


def test_cidade_uf_cep():
    assert n.cidade("São João del-Rei") == "saojoaodelrei"
    assert n.cidade("") is None
    assert n.uf("MG") == "mg"
    assert n.uf("Minas") is None
    assert n.cep("38.400-123") == "38400123"
    assert n.cep("123") is None


def test_sha():
    assert n.sha("") == ""
    assert n.sha(None) == ""
    assert n.sha("br") == hashlib.sha256(b"br").hexdigest()


def test_fatos_from_row():
    f = Fatos.from_row({
        "lead_id": "l1", "ultima_compra": "2026-10-01T12:00:00+00:00", "receita_365": "123.4",
        "nome": "Ana", "lead_phone": None, "lead_email": None, "segmento": None,
        "docs": ["123"], "fones_bling": [], "emails_bling": [],
        "contatos_bling": [{"account": "default", "id": 9}],
    })
    assert f.ultima_compra == datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    assert f.receita_365 == 123.4
    assert f.contatos_bling == [("default", 9)]
    assert f.pipeline_pl is False


def test_audiences_fixos():
    assert {a.key: a.audience_id for a in AUDIENCES} == {
        "meta_pl": "120252789539440163", "meta_atacado": "120252789580640163",
        "google_pl": "9496018532", "google_atacado": "9496602202"}
