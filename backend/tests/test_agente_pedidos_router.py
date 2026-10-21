import json

import pytest
from fastapi.testclient import TestClient

from app.agente_pedidos import auth, confirmar, leitura, rascunhos
from app.main import app
from tests.agente_pedidos_fakes import ESPELHO, FakeBling, FakeRedis, FakeSupabase

H = {"X-Agente-Token": "segredo"}
AUTOR = {"discord_id": "123", "nome": "Ana"}
BASE = "/api/agente-pedidos"


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_FABRICA_CONTATO_ID", "900")
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", "segredo", raising=False)
    sb = FakeSupabase(ESPELHO)
    monkeypatch.setattr(leitura, "get_supabase", lambda: sb)
    redis = FakeRedis()
    monkeypatch.setattr(rascunhos, "get_redis", lambda: redis)
    monkeypatch.setattr(rascunhos, "hoje", lambda: "2026-10-21")
    cliente = TestClient(app)
    cliente.redis = redis
    return cliente


def test_sem_header_401(http):
    r = http.get(f"{BASE}/contas")
    assert r.status_code == 401
    assert r.json() == {"erro": "token", "mensagem": "token inválido"}


def test_token_errado_401(http):
    assert http.get(f"{BASE}/contas", headers={"X-Agente-Token": "x"}).status_code == 401


def test_sem_token_configurado_503(http, monkeypatch):
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", None, raising=False)
    r = http.get(f"{BASE}/contas", headers=H)
    assert r.status_code == 503
    assert r.json()["erro"] == "nao_configurado"


def test_todas_as_rotas_exigem_token(http):
    rotas = [("get", "/contas"), ("get", "/clientes?conta=default&q=x"),
             ("get", "/produtos?conta=default&q=x"), ("get", "/vendedores?conta=default"),
             ("get", "/formas-pagamento?conta=default&finalidade=venda"),
             ("post", "/rascunhos/venda"), ("post", "/rascunhos/compra"),
             ("post", "/rascunhos/contato"), ("post", "/rascunhos/abcdef123456/confirmar"),
             ("get", "/rascunhos/abcdef123456/resultado"), ("delete", "/rascunhos/abcdef123456")]
    for metodo, rota in rotas:
        assert getattr(http, metodo)(BASE + rota).status_code == 401, rota


def test_contas(http):
    r = http.get(f"{BASE}/contas", headers=H)
    assert r.status_code == 200
    assert r.json() == [
        {"conta": "default", "apelido": "boaventura", "rotulo": "Bling Boaventura"},
        {"conta": "secundaria", "apelido": "caferural", "rotulo": "Bling Caferural"},
    ]


def test_leituras(http):
    r = http.get(f"{BASE}/clientes", params={"conta": "default", "q": "empório x"}, headers=H)
    assert [c["id"] for c in r.json()] == [10]
    r = http.get(f"{BASE}/produtos", params={"conta": "default", "q": "gourmet"}, headers=H)
    assert [p["id"] for p in r.json()] == [1]
    r = http.get(f"{BASE}/vendedores", params={"conta": "default"}, headers=H)
    assert r.json() == [{"id": 50, "nome": "João"}]
    r = http.get(f"{BASE}/formas-pagamento", params={"conta": "default", "finalidade": "compra"},
                 headers=H)
    assert [f["id"] for f in r.json()] == [101, 102]


def test_conta_desconhecida_400_no_topo(http):
    r = http.get(f"{BASE}/clientes", params={"conta": "outra", "q": "x"}, headers=H)
    assert r.status_code == 400
    assert r.json() == {"erro": "conta", "mensagem": "conta desconhecida: outra"}


def test_rascunho_de_venda_201(http):
    corpo = {"conta": "default", "cliente_id": 10,
             "itens": [{"produto_id": 1, "quantidade": 10}],
             "desconto": {"valor": 15, "unidade": "PERCENTUAL"}, "frete": 25,
             "forma_pagamento_id": 100, "prazos": [30, 60], "vendedor_id": 50, "autor": AUTOR}
    r = http.post(f"{BASE}/rascunhos/venda", json=corpo, headers=H)
    assert r.status_code == 201, r.text
    d = r.json()
    assert set(d) == {"id", "tipo", "conta", "expira_em", "resumo"}
    assert d["tipo"] == "venda" and d["conta"] == "default" and len(d["id"]) == 12
    assert d["resumo"]["total"] == 407.5  # 450 * 0,85 + 25
    assert len(d["resumo"]["parcelas"]) == 2
    assert set(d["resumo"]) == {
        "rotulo_conta", "parte", "linhas", "subtotal", "desconto", "desconto_valor", "frete",
        "total", "parcelas", "vendedor", "forma_pagamento", "data_prevista", "observacoes",
        "contato", "avisos"}
    assert "payload" not in d
    assert f"agente_pedidos:rascunho:{d['id']}" in http.redis.dados


def test_rascunho_de_compra_e_contato_201(http, monkeypatch):
    r = http.post(f"{BASE}/rascunhos/compra", headers=H, json={
        "conta": "default", "itens": [{"produto_id": 1, "quantidade": 3, "valor_unitario": 20}],
        "autor": AUTOR})
    assert r.status_code == 201, r.text
    assert r.json()["tipo"] == "compra" and r.json()["resumo"]["total"] == 60.0

    r = http.post(f"{BASE}/rascunhos/contato", headers=H, json={
        "conta": "default", "nome": "Café do Ponto", "documento": "45.723.174/0001-10",
        "autor": AUTOR})
    assert r.status_code == 201, r.text
    assert r.json()["resumo"]["contato"]["tipo"] == "J"


def test_erros_vem_no_topo(http):
    r = http.post(f"{BASE}/rascunhos/venda", headers=H, json={
        "conta": "default", "cliente_id": 999, "itens": [{"produto_id": 1, "quantidade": 1}],
        "forma_pagamento_id": 100, "prazos": [0], "autor": AUTOR})
    assert r.status_code == 404
    assert r.json() == {"erro": "cliente", "mensagem": "cliente 999 não existe nesta conta"}

    r = http.post(f"{BASE}/rascunhos/contato", headers=H, json={
        "conta": "default", "nome": "Dup", "documento": "11.222.333/0001-81", "autor": AUTOR})
    assert r.status_code == 409
    assert r.json()["erro"] == "contato_existe"
    assert r.json()["contato"] == {"id": 10, "nome": "Empório X Ltda"}


def test_validacao_do_corpo_vira_422_no_topo(http):
    r = http.post(f"{BASE}/rascunhos/venda", headers=H, json={"conta": "default"})
    assert r.status_code == 422
    d = r.json()
    assert set(d) == {"erro", "mensagem"} and d["erro"] == "validacao"
    assert "cliente_id" in d["mensagem"]


def test_confirmar_resultado_cancelar(http, monkeypatch):
    bling = FakeBling({("GET", "/pedidos/vendas"): {"data": []},
                       ("POST", "/pedidos/vendas"): {"data": {"id": 555, "numero": 1234}}})
    monkeypatch.setattr(confirmar, "novo_cliente", lambda conta: bling)
    criado = http.post(f"{BASE}/rascunhos/venda", headers=H, json={
        "conta": "default", "cliente_id": 10, "itens": [{"produto_id": 1, "quantidade": 1}],
        "forma_pagamento_id": 100, "prazos": [0], "autor": AUTOR}).json()
    id_ = criado["id"]

    assert http.get(f"{BASE}/rascunhos/{id_}/resultado", headers=H).json() == {"status": "pendente"}

    r = http.post(f"{BASE}/rascunhos/{id_}/confirmar", headers=H, json={"discord_id": "123"})
    assert r.status_code == 201
    assert r.json() == {"status": "criado", "bling_id": 555, "numero": "1234",
                        "link": "https://www.bling.com.br/vendas.php#edit/555"}
    assert http.get(f"{BASE}/rascunhos/{id_}/resultado", headers=H).json()["status"] == "criado"

    r = http.post(f"{BASE}/rascunhos/abcdef000000/confirmar", headers=H, json={"discord_id": "1"})
    assert r.status_code == 410 and r.json()["erro"] == "vencido"
    assert http.get(f"{BASE}/rascunhos/abcdef000000/resultado", headers=H).status_code == 410

    outro = http.post(f"{BASE}/rascunhos/venda", headers=H, json={
        "conta": "default", "cliente_id": 10, "itens": [{"produto_id": 1, "quantidade": 1}],
        "forma_pagamento_id": 100, "prazos": [0], "autor": AUTOR}).json()["id"]
    r = http.delete(f"{BASE}/rascunhos/{outro}", headers=H)
    assert r.status_code == 204 and r.content == b""
    assert http.delete(f"{BASE}/rascunhos/{outro}", headers=H).status_code == 410


def test_confirmar_na_fila_202(http, monkeypatch):
    http.redis.dados["agente_pedidos:resultado:abcdef123456"] = json.dumps({"status": "pendente"})
    r = http.post(f"{BASE}/rascunhos/abcdef123456/confirmar", headers=H, json={"discord_id": "1"})
    assert r.status_code == 202 and r.json() == {"status": "na_fila"}
