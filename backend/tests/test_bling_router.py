import asyncio

import pytest

import app.bling.router as br
from app.bling.contacts import Resolution
from app.bling.errors import BlingServerError, BlingValidationError


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.captured = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.captured.setdefault("eq", {})[c] = v
        return self

    def in_(self, c, v):
        self.captured["in"] = (c, list(v))
        return self

    def or_(self, expr):
        self.captured["or"] = expr
        return self

    def ilike(self, c, v):
        self.captured["ilike"] = (c, v)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.rows
        return r


class FakeSupabase:
    def __init__(self, por_tabela):
        self.por_tabela = por_tabela
        self.queries = []

    def table(self, name):
        q = FakeQuery(self.por_tabela.get(name, []))
        self.queries.append(q)
        return q


# O espelho de produtos e consultado pelo endpoint de pedido para completar a
# descricao dos itens (o Bling exige `descricao` mesmo com `produto.id`). Sem
# este duble, os testes de pedido bateriam no Supabase de verdade.
ESPELHO_PRODUTOS = {"bling_products": [
    {"id": 1, "nome": "Cafe Classico 250g", "codigo": "CAF250", "unidade": "UN"},
]}


def test_products_filtra_por_ativos_e_busca(monkeypatch):
    sb = FakeSupabase({"bling_products": [{"id": 1, "nome": "Cafe Classico 250g"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_products(q="classico"))

    assert out["data"][0]["nome"] == "Cafe Classico 250g"
    assert sb.queries[0].captured["eq"]["situacao"] == "A"


def test_products_sem_busca_nao_aplica_filtro_de_texto(monkeypatch):
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)
    asyncio.run(br.list_products(q=None))
    assert "or" not in sb.queries[0].captured


def test_payment_methods_so_recebimentos_e_ativas(monkeypatch):
    sb = FakeSupabase({"bling_payment_methods": [
        {"id": 45, "descricao": "Boleto", "situacao": 1, "finalidade": 2},
        {"id": 46, "descricao": "Fornecedor", "situacao": 1, "finalidade": 1},
        {"id": 47, "descricao": "Antiga", "situacao": 0, "finalidade": 2},
    ]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_payment_methods())

    ids = [m["id"] for m in out["data"]]
    assert ids == [45], "so formas ativas com finalidade de recebimento"


def test_criar_pedido_devolve_409_quando_contato_nao_resolve(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "cnpj": None})

    async def fake_resolve(lead):
        return Resolution("suggested", None, [{"id": 77, "nome": "Empresa X"}], "telefone")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 409
    corpo = resp.body.decode()
    assert "contact_unresolved" in corpo
    assert "Empresa X" in corpo


def test_criar_pedido_enfileira_quando_bling_esta_fora(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingServerError("bling fora do ar")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None):
        enfileirados.append(kind)

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 202
    assert enfileirados == ["create_order"]


def test_erro_de_validacao_nao_enfileira_e_devolve_422(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingValidationError("quantidade invalida", description="itens[0]")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None):
        enfileirados.append(kind)

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 422
    assert enfileirados == [], "erro de validacao nao pode virar retentativa"


def test_sucesso_devolve_201_com_numero_do_pedido(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    capturado = {}

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        capturado.update(k)
        return {"sale_id": "S1", "bling_order_id": 34215992, "bling_order_number": 1234}

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 201
    assert "1234" in resp.body.decode()
    # O Bling recusa item sem `descricao` mesmo quando o `produto.id` vai junto:
    # a descricao tem de ser completada a partir do espelho antes do POST.
    assert capturado["itens"][0]["descricao"] == "Cafe Classico 250g"
    assert capturado["itens"][0]["codigo"] == "CAF250"


def test_oauth_callback_rejeita_state_invalido(monkeypatch):
    async def fake_consume(state):
        return False

    monkeypatch.setattr(br.auth, "consume_state", fake_consume)
    resp = asyncio.run(br.oauth_callback(code="c", state="ruim"))
    assert resp.status_code == 400


def test_router_registrado_no_app():
    from app.main import app as fastapi_app
    rotas = {getattr(r, "path", "") for r in fastapi_app.routes}
    assert "/api/bling/products" in rotas
    assert "/api/bling/orders" in rotas
    assert "/api/bling/status" in rotas
