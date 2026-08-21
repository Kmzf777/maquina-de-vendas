import asyncio

import pytest

import app.bling.router as br
from app.bling.contacts import Resolution
from app.bling.errors import BlingServerError, BlingValidationError
from app.bling import contacts


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

    def update(self, values):
        self.captured["update"] = values
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


def test_busca_de_contato_sanitiza_o_termo():
    # Virgula e parentese COMPOEM a sintaxe do filtro `or` do PostgREST: sem
    # neutralizar, o resto do texto vira filtro.
    assert br._termo_seguro("Ltda, (ME)") == "Ltda   ME"


def test_contacts_search_filtra_no_espelho(monkeypatch):
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "Empresa X"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.search_contacts(q="empresa", id=None, limit=20))

    assert out["data"][0]["nome"] == "Empresa X"
    assert "empresa" in sb.queries[0].captured["or"].lower()


def test_contacts_search_sem_termo_nao_aplica_filtro_de_texto(monkeypatch):
    sb = FakeSupabase({"bling_contacts": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)
    asyncio.run(br.search_contacts(q=None, id=None, limit=20))
    assert "or" not in sb.queries[0].captured


def test_contacts_search_por_id_filtra_por_igualdade(monkeypatch):
    # A tela de detalhe do lead precisa achar o contato vinculado mesmo sem
    # CNPJ no lead (vinculo por telefone/e-mail/escolha manual) — id e exato.
    sb = FakeSupabase({"bling_contacts": [{"id": 42, "nome": "Empresa Y"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.search_contacts(id=42, limit=20))

    assert out["data"][0]["nome"] == "Empresa Y"
    assert sb.queries[0].captured["eq"]["id"] == 42


def test_contacts_search_por_id_ignora_filtro_de_texto(monkeypatch):
    # id e exato: combinar com o `or_` de texto nao faz sentido — id vence.
    sb = FakeSupabase({"bling_contacts": [{"id": 42, "nome": "Empresa Y"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    asyncio.run(br.search_contacts(q="qualquer coisa", id=42, limit=20))

    assert "or" not in sb.queries[0].captured
    assert sb.queries[0].captured["eq"]["id"] == 42


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
        lead_id="L1", deal_id="D1", conversation_id="CONV-9",
        sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 201
    assert "1234" in resp.body.decode()
    # A conversa de origem tem de atravessar o router ate a `sales`: e o vinculo
    # entre a venda e o atendimento que a gerou, que o POST /api/sales ja grava.
    assert capturado["conversation_id"] == "CONV-9"
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


def test_unlink_limpa_o_vinculo_do_lead(monkeypatch):
    sb = FakeSupabase({})
    monkeypatch.setattr(contacts, "get_supabase", lambda: sb)

    asyncio.run(contacts.unlink("lead-1"))

    q = sb.queries[0]
    assert q.captured["update"] == {"bling_contact_id": None}
    assert q.captured["eq"] == {"id": "lead-1"}


def test_unlink_endpoint_devolve_unlinked(monkeypatch):
    chamadas = []

    async def fake_unlink(lead_id):
        chamadas.append(lead_id)

    monkeypatch.setattr(br.contacts, "unlink", fake_unlink)

    resp = asyncio.run(br.unlink_contact_endpoint(lead_id="lead-1"))

    assert resp == {"unlinked": True}
    assert chamadas == ["lead-1"]


def test_router_registrado_no_app():
    """O router precisa estar montado no app.

    Guarda em NIVEL DE FONTE (mesma convencao de test_cadence_definition_api_2026_07_10):
    inspecionar `app.main.app.routes` em runtime e fragil a poluicao de modulos entre
    testes — o app pode chegar aqui parcialmente montado por outro teste, e ai a asserticao
    falha SO no runner do CI (foi exatamente o que derrubou o deploy em 21/08/2026).

    As rotas em si continuam cobertas pelos testes de comportamento deste arquivo."""
    import inspect
    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.bling.router import router as bling_router" in src
    assert "app.include_router(bling_router)" in src


def test_router_expoe_as_rotas_esperadas():
    """Prefixo e paths do proprio router (objeto isolado, imune a poluicao de modulos)."""
    from app.bling.router import router as bling_router

    rotas = {r.path for r in bling_router.routes}
    assert "/api/bling/products" in rotas
    assert "/api/bling/orders" in rotas
    assert "/api/bling/status" in rotas
