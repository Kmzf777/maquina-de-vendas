import asyncio
from decimal import Decimal

import pytest

import app.bling.orders as orders
from app.bling.errors import BlingValidationError


# ---------- parcelas ----------

def test_a_vista_gera_uma_parcela_na_data_da_venda():
    p = orders.build_installments(Decimal("500.00"), [0], 45, "2026-08-18")
    assert p == [{"dataVencimento": "2026-08-18", "valor": 500.0,
                  "formaPagamento": {"id": 45}}]


def test_30_60_divide_em_duas_e_soma_datas():
    p = orders.build_installments(Decimal("500.00"), [30, 60], 45, "2026-08-18")
    assert [x["dataVencimento"] for x in p] == ["2026-09-17", "2026-10-17"]
    assert [x["valor"] for x in p] == [250.0, 250.0]


def test_ultima_parcela_absorve_o_arredondamento():
    """100,00 em 3x = 33,33 + 33,33 + 33,34. A soma tem que fechar EXATO —
    se sobrar 1 centavo, o Bling recusa o pedido."""
    p = orders.build_installments(Decimal("100.00"), [30, 60, 90], 45, "2026-08-18")
    assert [x["valor"] for x in p] == [33.33, 33.33, 33.34]
    assert round(sum(x["valor"] for x in p), 2) == 100.00


def test_arredondamento_para_baixo_tambem_fecha():
    p = orders.build_installments(Decimal("10.00"), [0, 30, 60], 45, "2026-08-18")
    assert round(sum(x["valor"] for x in p), 2) == 10.00


def test_parcelas_exige_forma_de_pagamento():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [0], None, "2026-08-18")


def test_parcelas_exige_pelo_menos_um_prazo():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [], 45, "2026-08-18")


def test_parse_terms_aceita_string_do_bling():
    assert orders.parse_terms("30/60/90") == [30, 60, 90]
    assert orders.parse_terms("0") == [0]
    assert orders.parse_terms("") == [0]
    assert orders.parse_terms("a vista") == [0]


# ---------- total e itens ----------

def test_total_do_item_aplica_desconto_percentual():
    total = orders.item_total({"quantidade": 10, "valor_unitario": 26.70,
                               "desconto_percentual": 10})
    assert total == Decimal("240.30")


def test_total_do_pedido_soma_itens():
    itens = [
        {"quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0},
        {"quantidade": 2, "valor_unitario": 50.00, "desconto_percentual": 0},
    ]
    assert orders.order_total(itens) == Decimal("367.00")


def test_resumo_de_produto_para_a_coluna_product():
    assert orders.product_summary([{"descricao": "Cafe Classico 250g"}]) == "Cafe Classico 250g"
    assert orders.product_summary([
        {"descricao": "Cafe Classico 250g"}, {"descricao": "Cafe Suave 500g"},
        {"descricao": "Drip Coffee"},
    ]) == "Cafe Classico 250g +2 itens"
    assert orders.product_summary([]) == "Pedido Bling"


# ---------- payload ----------

def test_payload_tem_os_campos_obrigatorios_do_bling(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: 203455519)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: 6)

    payload = orders.build_order_payload(
        contact_id=5845664414,
        sold_at="2026-08-18",
        itens=[{"bling_product_id": 123, "codigo": "CAN-250", "descricao": "Cafe 250g",
                "unidade": "UN", "quantidade": 10, "valor_unitario": 26.70,
                "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30]},
        seller_id=7,
        notes="obs do cliente",
        internal_notes="CRM lead L1",
    )

    # obrigatorios segundo o OpenAPI: contato, data, dataSaida, dataPrevista, itens, parcelas
    assert payload["contato"] == {"id": 5845664414}
    assert payload["data"] == payload["dataSaida"] == payload["dataPrevista"] == "2026-08-18"
    assert payload["itens"][0]["produto"] == {"id": 123}
    assert payload["itens"][0]["descricao"] == "Cafe 250g"
    assert payload["itens"][0]["quantidade"] == 10
    assert payload["itens"][0]["valor"] == 26.70
    assert payload["parcelas"][0]["formaPagamento"] == {"id": 45}
    assert payload["vendedor"] == {"id": 7}
    assert payload["loja"] == {"id": 203455519}
    assert payload["situacao"]["id"] == 6
    assert payload["observacoes"] == "obs do cliente"
    assert payload["observacoesInternas"] == "CRM lead L1"


def test_payload_omite_loja_e_situacao_quando_nao_configurados(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    payload = orders.build_order_payload(
        contact_id=1, sold_at="2026-08-18",
        itens=[{"bling_product_id": 1, "descricao": "X", "quantidade": 1,
                "valor_unitario": 10.0, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [0]}, seller_id=None,
    )
    assert "loja" not in payload
    assert "situacao" not in payload
    assert "vendedor" not in payload


def test_payload_recusa_pedido_sem_itens():
    with pytest.raises(BlingValidationError):
        orders.build_order_payload(contact_id=1, sold_at="2026-08-18", itens=[],
                                   payment={"method_id": 45, "terms": [0]}, seller_id=None)


# ---------- criacao e projecao ----------

class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.captured = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.captured.setdefault("eq", {})[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def insert(self, payload):
        self.captured["insert"] = payload
        self.store.setdefault(self.name + "_inserts", []).append(payload)
        return self

    def update(self, payload):
        self.captured["update"] = payload
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def upsert(self, payload, on_conflict=None):
        self.captured["upsert"] = payload
        self.store.setdefault(self.name + "_upserts", []).append(payload)
        self.store["on_conflict_" + self.name] = on_conflict
        return self

    def delete(self):
        self.captured["delete"] = True
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [{"id": "SALE-1"}])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


def test_create_order_persiste_venda_e_itens(monkeypatch):
    store = {}
    # Instancia unica fora do lambda: `lambda: FakeSupabase(store)` construiria um
    # objeto novo a cada chamada e esconderia estado acumulado dentro do fake.
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    class FakeClient:
        async def post(self, path, json=None):
            assert path == "/pedidos/vendas"
            return {"data": {"id": 34215992}}

        async def get(self, path, params=None):
            assert path == "/pedidos/vendas/34215992"
            return {"data": {"id": 34215992, "numero": 1234,
                             "situacao": {"id": 6, "valor": 6}, "total": 267.0}}

    itens = [{"bling_product_id": 123, "codigo": "CAN-250", "descricao": "Cafe 250g",
              "quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0}]

    out = asyncio.run(orders.create_order(
        FakeClient(),
        lead_id="L1", deal_id="D1", contact_id=555, sold_at="2026-08-18",
        sold_by="v@e.com", itens=itens,
        payment={"method_id": 45, "terms": [30]}, seller_id=None,
    ))

    assert out["bling_order_id"] == 34215992
    assert out["bling_order_number"] == 1234
    venda = store["sales_inserts"][0]
    assert venda["origin"] == "crm"
    assert venda["status"] == "registrada"
    assert venda["value"] == 267.0
    assert venda["product"] == "Cafe 250g"
    assert venda["bling_order_id"] == 34215992
    assert len(store["sale_items_inserts"][0]) == 1


def test_upsert_from_bling_marca_origin_bling_para_venda_nova(monkeypatch):
    store = {"row_sales": []}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    pedido = {
        "id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
        "contato": {"id": 555}, "situacao": {"id": 9, "valor": 9},
        "itens": [{"produto": {"id": 1}, "codigo": "A", "descricao": "Item A",
                   "quantidade": 3, "valor": 50.0, "desconto": 0}],
    }
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    linha = store["sales_upserts"][0]
    assert linha["origin"] == "bling"
    assert linha["bling_order_id"] == 999
    assert linha["deal_id"] is None, "venda vinda do ERP entra sem deal (decisao D7)"
    assert store["on_conflict_sales"] == "bling_order_id"


def test_upsert_from_bling_preserva_origin_crm_de_venda_existente(monkeypatch):
    store = {"row_sales": [{"id": "SALE-1", "origin": "crm", "deal_id": "D1"}]}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    pedido = {"id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
              "contato": {"id": 555}, "situacao": {"id": 9}, "itens": []}
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    linha = store["sales_upserts"][0]
    assert linha["origin"] == "crm", "o webhook de volta nao pode reescrever a origem"
    assert linha["deal_id"] == "D1"


def test_cancel_marca_status_sem_apagar(monkeypatch):
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)
    asyncio.run(orders.cancel_from_bling(999, event_date="2026-08-11T10:00:00Z"))
    assert store["sales_updates"][0]["status"] == "cancelada"
