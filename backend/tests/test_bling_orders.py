import asyncio
from decimal import Decimal

import pytest

import app.bling.orders as orders
from app.bling.errors import BlingServerError, BlingValidationError


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


def test_parcelas_recusam_divisao_sem_centavos_suficientes():
    """R$0,03 em 4x deixaria a ULTIMA parcela negativa (0,01+0,01+0,01-0,01).

    Recusar aqui e melhor do que deixar o Bling recusar: o erro que ele devolve
    nao menciona parcelas, e o vendedor fica olhando um erro generico sem saber
    que o problema e a divisao.
    """
    # fronteira de baixo: 4 centavos em 4x ainda da 1 centavo por parcela
    p = orders.build_installments(Decimal("0.04"), [0, 30, 60, 90], 45, "2026-08-18")
    assert [x["valor"] for x in p] == [0.01, 0.01, 0.01, 0.01]

    # um centavo a menos e a divisao deixa de caber
    with pytest.raises(BlingValidationError) as exc:
        orders.build_installments(Decimal("0.03"), [0, 30, 60, 90], 45, "2026-08-18")
    assert "0,03" in str(exc.value), "a mensagem precisa citar o valor"
    assert "4" in str(exc.value), "a mensagem precisa citar o numero de parcelas"


def test_parcelas_recusam_divisao_que_zera_alguma_parcela():
    """Ter centavos sobrando nao basta. Duas divisoes escapam de uma checagem
    ingenua de 'total em centavos >= n':

    - 0,06 em 4x: a base arredonda para 0,02 e a ULTIMA fica 0,00;
    - 0,03 em 12x: a base arredonda para 0,00 e ONZE parcelas ficam zeradas.
    """
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("0.06"), [0, 30, 60, 90], 45, "2026-08-18")
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("0.03"), [30 * i for i in range(12)],
                                  45, "2026-08-18")


def test_toda_divisao_aceita_tem_parcelas_positivas_e_soma_exata():
    """Trava de regressao sobre o invariante real: o que a funcao ACEITA nunca
    tem parcela <= 0 e sempre soma exatamente o total."""
    aceitas = 0
    for cents in range(1, 300):
        total = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
        for n in (1, 2, 3, 4, 6, 12):
            try:
                p = orders.build_installments(
                    total, [30 * i for i in range(n)], 45, "2026-08-18")
            except BlingValidationError:
                continue  # divisao recusada na origem — comportamento esperado
            aceitas += 1
            assert all(x["valor"] > 0 for x in p), (total, n, p)
            soma = sum((Decimal(str(x["valor"])) for x in p), Decimal("0"))
            assert soma == total, (total, n, soma)
    assert aceitas > 1000, "a varredura precisa exercitar divisoes de verdade"


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


def test_parcelas_dividem_o_total_liquido_com_desconto_em_reais(monkeypatch):
    """Itens de R$267,00 com R$67,00 de desconto = pedido de R$200,00. Parcelar
    o BRUTO cobraria R$67 a mais do que o pedido vale."""
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    payload = orders.build_order_payload(
        contact_id=1, sold_at="2026-08-18",
        itens=[{"bling_product_id": 1, "descricao": "Cafe 250g", "quantidade": 10,
                "valor_unitario": 26.70, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30, 60]}, seller_id=None,
        discount={"valor": 67.00, "unidade": "REAL"},
    )

    assert [x["valor"] for x in payload["parcelas"]] == [100.0, 100.0]
    assert sum(x["valor"] for x in payload["parcelas"]) == 200.00
    assert payload["desconto"] == {"valor": 67.0, "unidade": "REAL"}


def test_parcelas_dividem_o_total_liquido_com_desconto_percentual(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    payload = orders.build_order_payload(
        contact_id=1, sold_at="2026-08-18",
        itens=[{"bling_product_id": 1, "descricao": "Cafe 250g", "quantidade": 10,
                "valor_unitario": 26.70, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30, 60]}, seller_id=None,
        discount={"valor": 10, "unidade": "PERCENTUAL"},
    )

    # 267,00 - 10% = 240,30 -> 120,15 + 120,15
    assert [x["valor"] for x in payload["parcelas"]] == [120.15, 120.15]
    assert round(sum(x["valor"] for x in payload["parcelas"]), 2) == 240.30


def test_desconto_liquido_e_calculado_em_decimal():
    assert orders.apply_discount(Decimal("267.00"), None) == Decimal("267.00")
    assert orders.apply_discount(Decimal("267.00"), {"valor": 0}) == Decimal("267.00")
    assert orders.apply_discount(
        Decimal("267.00"), {"valor": 67, "unidade": "REAL"}) == Decimal("200.00")
    assert orders.apply_discount(
        Decimal("267.00"), {"valor": 10, "unidade": "PERCENTUAL"}) == Decimal("240.30")
    # unidade ausente cai em REAL, como o payload enviado ao Bling
    assert orders.apply_discount(
        Decimal("100.00"), {"valor": 25}) == Decimal("75.00")


def test_desconto_maior_que_o_total_e_recusado(monkeypatch):
    """Liquido negativo nao vira pedido: a guarda de parcelas recusa."""
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    with pytest.raises(BlingValidationError):
        orders.build_order_payload(
            contact_id=1, sold_at="2026-08-18",
            itens=[{"bling_product_id": 1, "descricao": "X", "quantidade": 1,
                    "valor_unitario": 10.0, "desconto_percentual": 0}],
            payment={"method_id": 45, "terms": [0]}, seller_id=None,
            discount={"valor": 50.00, "unidade": "REAL"},
        )


def test_payload_recusa_pedido_sem_itens():
    with pytest.raises(BlingValidationError):
        orders.build_order_payload(contact_id=1, sold_at="2026-08-18", itens=[],
                                   payment={"method_id": 45, "terms": [0]}, seller_id=None)


def test_payload_recusa_item_sem_vinculo_com_o_bling():
    """Produto do CRM sem mapeamento no Bling faria int(None) -> TypeError -> 500.
    A mensagem cita a descricao para o vendedor saber QUAL produto corrigir."""
    # campo ausente
    with pytest.raises(BlingValidationError) as exc:
        orders.build_order_payload(
            contact_id=1, sold_at="2026-08-18",
            itens=[{"descricao": "Cafe Sem Vinculo 250g", "quantidade": 1,
                    "valor_unitario": 10.0, "desconto_percentual": 0}],
            payment={"method_id": 45, "terms": [0]}, seller_id=None)
    assert "Cafe Sem Vinculo 250g" in str(exc.value)

    # campo presente porem None
    with pytest.raises(BlingValidationError) as exc2:
        orders.build_order_payload(
            contact_id=1, sold_at="2026-08-18",
            itens=[{"bling_product_id": None, "descricao": "Drip Sem Vinculo",
                    "quantidade": 1, "valor_unitario": 10.0, "desconto_percentual": 0}],
            payment={"method_id": 45, "terms": [0]}, seller_id=None)
    assert "Drip Sem Vinculo" in str(exc2.value)


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
        # registrado no store para o teste conseguir afirmar que NENHUM delete
        # aconteceu (webhook resumido nao pode apagar sale_items)
        self.store.setdefault(self.name + "_deletes", []).append(True)
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
            # `total` DIVERGENTE dos itens de proposito: se o codigo tirar o
            # dinheiro daqui em vez de calcular dos itens, o assert de `value`
            # abaixo reprova.
            return {"data": {"id": 34215992, "numero": 1234,
                             "situacao": {"id": 6, "valor": 6}, "total": 999.99}}

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
    assert venda["value"] == 267.0, "o valor vem dos itens (10 x 26,70), nao do GET"
    assert venda["product"] == "Cafe 250g"
    assert venda["bling_order_id"] == 34215992
    assert venda["lead_id"] == "L1" and venda["deal_id"] == "D1"
    assert venda["payment_method_id"] == 45
    assert venda["payment_terms"] == "30"

    # os VALORES do item, nao so a contagem de linhas
    linhas = store["sale_items_inserts"][0]
    assert len(linhas) == 1
    assert linhas[0]["bling_product_id"] == 123
    assert linhas[0]["descricao"] == "Cafe 250g"
    assert linhas[0]["quantidade"] == 10.0
    assert linhas[0]["valor_unitario"] == 26.70
    assert linhas[0]["total"] == 267.0
    assert linhas[0]["ordem"] == 0
    assert linhas[0]["sale_id"] == "SALE-1"

    # o GET so enriquece: numero e situacao entram por UPDATE depois do insert
    assert store["sales_inserts"][0]["bling_order_number"] is None
    assert store["sales_updates"][0] == {"bling_order_number": 1234,
                                         "bling_situacao_id": 6}


def test_create_order_grava_a_venda_mesmo_se_o_get_de_detalhe_falhar(monkeypatch):
    """O POST sucedeu: o pedido JA existe no ERP. Se o GET seguinte falhar com
    erro transitorio e a excecao subir, a `sales` nunca e gravada e o worker de
    fila retenta — fazendo um SEGUNDO POST e duplicando o pedido no Bling.

    O bling_order_id precisa estar persistido antes de qualquer coisa que possa
    falhar; numero e situacao sao cosmeticos e o webhook os completa.
    """
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    class FakeClientGetQuebrado:
        async def post(self, path, json=None):
            return {"data": {"id": 34215992}}

        async def get(self, path, params=None):
            raise BlingServerError("504 do Bling")

    out = asyncio.run(orders.create_order(
        FakeClientGetQuebrado(),
        lead_id="L1", deal_id=None, contact_id=555, sold_at="2026-08-18",
        sold_by="v@e.com",
        itens=[{"bling_product_id": 123, "descricao": "Cafe 250g", "quantidade": 10,
                "valor_unitario": 26.70, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30]}, seller_id=None,
    ))

    venda = store["sales_inserts"][0]
    assert venda["bling_order_id"] == 34215992, "o id do pedido nao pode se perder"
    assert venda["bling_order_number"] is None
    assert venda["bling_situacao_id"] is None
    assert venda["value"] == 267.0
    assert out["bling_order_id"] == 34215992
    assert out["bling_order_number"] is None
    # nada de UPDATE de enriquecimento, porque o GET falhou
    assert "sales_updates" not in store


def test_create_order_desconta_o_cabecalho_do_valor_gravado(monkeypatch):
    """Desconto de cabecalho tem que sair de `sales.value` tambem — senao o CRM
    grava receita inflada em toda venda com desconto."""
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    class FakeClient:
        async def post(self, path, json=None):
            return {"data": {"id": 1}}

        async def get(self, path, params=None):
            return {"data": {"id": 1, "numero": 7, "situacao": {"id": 6}}}

    asyncio.run(orders.create_order(
        FakeClient(),
        lead_id="L1", deal_id=None, contact_id=555, sold_at="2026-08-18",
        sold_by=None,
        itens=[{"bling_product_id": 123, "descricao": "Cafe 250g", "quantidade": 10,
                "valor_unitario": 26.70, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [0]}, seller_id=None,
        discount={"valor": 67.00, "unidade": "REAL"},
    ))

    assert store["sales_inserts"][0]["value"] == 200.0, "267,00 - 67,00 de desconto"


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


def test_upsert_com_itens_substitui_os_sale_items(monkeypatch):
    """Contrapartida do teste do payload resumido: quando o pedido TRAZ itens,
    os sale_items sao de fato trocados pelos do Bling (delete + insert)."""
    store = {"row_sales": [{"id": "SALE-1", "origin": "bling", "deal_id": None,
                            "status": "registrada"}]}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    pedido = {
        "id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
        "situacao": {"id": 9},
        "itens": [{"produto": {"id": 1}, "codigo": "A", "descricao": "Item A",
                   "quantidade": 3, "valor": 50.0, "desconto": 0}],
    }
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    assert store["sale_items_deletes"] == [True], "os itens antigos saem"
    linhas = store["sale_items_inserts"][0]
    assert len(linhas) == 1
    assert linhas[0]["descricao"] == "Item A"
    assert linhas[0]["quantidade"] == 3.0
    assert linhas[0]["valor_unitario"] == 50.0
    assert linhas[0]["total"] == 150.0
    assert linhas[0]["sale_id"] == "SALE-1"
    assert store["sales_upserts"][0]["product"] == "Item A"


def test_upsert_resumido_nao_apaga_itens_nem_reescreve_o_produto(monkeypatch):
    """order.updated costuma vir com corpo resumido, SEM `itens`. O DELETE
    incondicional zerava os sale_items de uma venda que o CRM tinha acabado de
    gravar completa, e ainda trocava `product` por "Pedido Bling"."""
    store = {"row_sales": [{"id": "SALE-1", "origin": "crm", "deal_id": "D1",
                            "status": "registrada"}]}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    # payload magro: sem a chave `itens`
    pedido = {"id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0,
              "situacao": {"id": 9}}
    asyncio.run(orders.upsert_from_bling(pedido, lead_id="L1",
                                         event_date="2026-08-10T10:00:00Z"))

    assert "sale_items_deletes" not in store, "webhook resumido nao apaga itens"
    assert "sale_items_inserts" not in store
    linha = store["sales_upserts"][0]
    assert "product" not in linha, "o resumo do produto existente e preservado"


def test_upsert_de_venda_nova_sem_itens_ainda_preenche_product(monkeypatch):
    """`product` e NOT NULL: venda que nasce pelo webhook sem itens precisa de
    algum resumo."""
    store = {"row_sales": []}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    asyncio.run(orders.upsert_from_bling(
        {"id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0},
        lead_id="L1", event_date="2026-08-10T10:00:00Z"))

    assert store["sales_upserts"][0]["product"] == "Pedido Bling"


def test_upsert_preserva_status_cancelada(monkeypatch):
    """Venda cancelada nao volta a 'registrada' no proximo evento do pedido."""
    store = {"row_sales": [{"id": "SALE-1", "origin": "bling", "deal_id": None,
                            "status": "cancelada"}]}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    asyncio.run(orders.upsert_from_bling(
        {"id": 999, "numero": 77, "data": "2026-08-10", "total": 150.0, "itens": []},
        lead_id="L1", event_date="2026-08-11T10:00:00Z"))

    assert store["sales_upserts"][0]["status"] == "cancelada"


def test_upsert_sem_data_no_pedido_nao_grava_string_none(monkeypatch):
    """Sem guarda, `data` ausente virava "NoneT12:00:00+00:00" e quebrava no
    Postgres no meio do processamento do webhook."""
    store = {"row_sales": []}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)

    asyncio.run(orders.upsert_from_bling(
        {"id": 999, "numero": 77, "total": 150.0, "itens": []},
        lead_id="L1", event_date="2026-08-11T10:00:00Z"))

    linha = store["sales_upserts"][0]
    assert "None" not in str(linha.get("sold_at"))
    assert linha["sold_at"] == "2026-08-11T10:00:00Z", "cai para a data do evento"


def test_cancel_marca_status_sem_apagar(monkeypatch):
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(orders, "get_supabase", lambda: fake_db)
    asyncio.run(orders.cancel_from_bling(999, event_date="2026-08-11T10:00:00Z"))

    # conjunto EXATO de chaves: o cancelamento nao pode zerar valor, apagar
    # lead_id nem mexer em nada alem do status e da data do evento
    assert store["sales_updates"] == [{"status": "cancelada",
                                       "bling_event_date": "2026-08-11T10:00:00Z"}]
    assert "sales_deletes" not in store
    assert "sale_items_deletes" not in store
