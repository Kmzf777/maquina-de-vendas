"""Contrato Onda 0 (b67f1c6b): cadastro único de vendedores (app.vendedores.service)."""
import pytest

from app.vendedores import service

JOAO = {"id": "u-joao", "email": "joao@cafecanastra.com", "nome": "João Brás",
        "apelidos": ["Joao Bras", "João - Café Canastra"], "segmentos": ["atacado", "private_label"],
        "atende_no_crm": True, "ativo": True}
ARTHUR = {"id": "u-arthur", "email": "arthur@cafecanastra.com", "nome": "Arthur",
          "apelidos": ["Arthur - Café Canastra"], "segmentos": ["exportacao"],
          "atende_no_crm": False, "ativo": True}
RAFAEL = {"id": "u-rafael", "email": "rafael@cafecanastra.com", "nome": "Rafael", "apelidos": [],
          "segmentos": [], "atende_no_crm": True, "ativo": False}


@pytest.fixture(autouse=True)
def tabela(monkeypatch):
    linhas = [JOAO, ARTHUR, RAFAEL]
    chamadas = []

    def fake():
        chamadas.append(1)
        return [dict(r) for r in linhas]

    service.limpar_cache()
    monkeypatch.setattr(service, "_carregar", fake)
    yield {"linhas": linhas, "chamadas": chamadas}
    service.limpar_cache()


def test_resolve_por_uuid():
    assert service.resolver_vendedor("u-joao") == "u-joao"


def test_resolve_por_email_case_insensitive():
    assert service.resolver_vendedor("JOAO@cafecanastra.com") == "u-joao"


@pytest.mark.parametrize("chave", ["Joao Bras", "João Brás", "João - Café Canastra", "  joão   brás "])
def test_resolve_por_nome_e_apelido(chave):
    assert service.resolver_vendedor(chave) == "u-joao"


def test_resolve_pelo_primeiro_token():
    assert service.resolver_vendedor("arthur") == "u-arthur"
    assert service.resolver_vendedor("joão") == "u-joao"


def test_resolve_inativo_tambem():
    assert service.resolver_vendedor("Rafael") == "u-rafael"


@pytest.mark.parametrize("chave", ["Vendedor", None, "", "   "])
def test_nao_resolve(chave):
    assert service.resolver_vendedor(chave) is None


def test_ambiguo_devolve_none(tabela):
    tabela["linhas"].extend([
        {"id": "u-ana1", "email": "ana1@x.com", "nome": "Ana Souza", "apelidos": [], "segmentos": [],
         "atende_no_crm": True, "ativo": True},
        {"id": "u-ana2", "email": "ana2@x.com", "nome": "Ana Lima", "apelidos": [], "segmentos": [],
         "atende_no_crm": True, "ativo": True},
    ])
    assert service.resolver_vendedor("Ana") is None
    assert service.resolver_vendedor("Ana Lima") == "u-ana2"


def test_vendedor_do_segmento():
    assert service.vendedor_do_segmento("exportacao")["id"] == "u-arthur"
    assert service.vendedor_do_segmento("private_label")["id"] == "u-joao"
    assert service.vendedor_do_segmento("consumo") is None
    assert service.vendedor_do_segmento(None) is None


def test_vendedor_do_segmento_ignora_inativo(tabela):
    tabela["linhas"].insert(0, {"id": "u-velho", "email": "v@x.com", "nome": "Velho", "apelidos": [],
                                "segmentos": ["atacado"], "atende_no_crm": True, "ativo": False})
    assert service.vendedor_do_segmento("atacado")["id"] == "u-joao"


def test_listar_e_por_id():
    assert [r["id"] for r in service.listar()] == ["u-joao", "u-arthur", "u-rafael"]
    assert [r["id"] for r in service.listar(ativos=True)] == ["u-joao", "u-arthur"]
    assert [r["id"] for r in service.listar(ativos=False)] == ["u-rafael"]
    assert service.por_id("u-arthur")["nome"] == "Arthur"
    assert service.por_id("u-nada") is None
    assert service.por_id(None) is None


def test_cache_e_limpar_cache(tabela):
    service.listar()
    service.resolver_vendedor("arthur")
    assert len(tabela["chamadas"]) == 1
    service.limpar_cache()
    service.listar()
    assert len(tabela["chamadas"]) == 2


def test_carregar_fail_soft(monkeypatch):
    monkeypatch.undo()
    service.limpar_cache()

    class Boom:
        def table(self, *a, **k): raise RuntimeError("x")
    monkeypatch.setattr(service, "get_supabase", lambda: Boom())
    assert service.listar() == []
    assert service.resolver_vendedor("arthur") is None
