import asyncio

import app.bling.products as prod


class FakeTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._filters = {}

    def upsert(self, rows, on_conflict=None):
        self.store.setdefault(self.name, []).extend(rows)
        self.store["on_conflict"] = on_conflict
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name)
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeTable(self.store, name)


class FakeClient:
    def __init__(self, itens):
        self.itens = itens
        self.params = None

    async def paginate(self, path, params=None, limite=100):
        self.params = params
        for item in self.itens:
            yield item


def test_mapeia_campos_do_bling_para_a_tabela():
    bruto = {
        "id": 123, "nome": "Cafe Canastra Classico Moido 250g", "codigo": "CAN-CLA-250",
        "preco": 26.7, "tipo": "P", "situacao": "A", "formato": "S",
        "idProdutoPai": 0, "descricaoCurta": "", "imagemURL": "https://x/y.jpg",
        "estoque": {"saldoVirtualTotal": 480.0},
    }
    row = prod.map_product(bruto)
    assert row["id"] == 123
    assert row["codigo"] == "CAN-CLA-250"
    assert row["nome"] == "Cafe Canastra Classico Moido 250g"
    assert row["preco"] == 26.7
    assert row["situacao"] == "A"
    assert row["saldo_virtual"] == 480.0
    assert row["imagem_url"] == "https://x/y.jpg"
    # idProdutoPai 0 significa "sem pai" no Bling — nao pode virar FK falsa
    assert row["id_produto_pai"] is None


def test_sync_completo_usa_criterio_5_e_faz_upsert(monkeypatch):
    store = {}
    client = FakeClient([
        {"id": 1, "nome": "A", "situacao": "A"},
        {"id": 2, "nome": "B", "situacao": "I"},
    ])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(prod.sync_products(client, full=True))

    assert n == 2
    # criterio=5 => "Todos" (inclui inativos). Produto inativo precisa ficar no
    # espelho para pedidos antigos e o backfill resolverem a descricao.
    assert client.params["criterio"] == 5
    assert store["on_conflict"] == "id"
    assert len(store["bling_products"]) == 2


def test_sync_incremental_manda_data_alteracao_inicial(monkeypatch):
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-17T00:00:00+00:00"}}
    client = FakeClient([{"id": 9, "nome": "C", "situacao": "A"}])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(prod.sync_products(client, full=False))

    assert client.params["dataAlteracaoInicial"] == "2026-08-17T00:00:00+00:00"
    assert "criterio" not in client.params


def test_sem_estado_anterior_cai_para_sync_completo(monkeypatch):
    store = {}
    client = FakeClient([{"id": 1, "nome": "A", "situacao": "A"}])
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(prod, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(prod.sync_products(client, full=False))

    assert client.params["criterio"] == 5


def test_apply_webhook_product_faz_upsert(monkeypatch):
    store = {}
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    payload = {"id": 55, "nome": "Novo", "codigo": "X", "preco": 9.9,
               "situacao": "A", "tipo": "P", "formato": "S"}
    asyncio.run(prod.apply_product_event("product.updated", payload))
    assert store["bling_products"][0]["id"] == 55


def test_apply_webhook_deleted_marca_inativo(monkeypatch):
    store = {}
    monkeypatch.setattr(prod, "get_supabase", lambda: FakeSupabase(store))
    asyncio.run(prod.apply_product_event("product.deleted", {"id": 55}))
    assert store["bling_products"][0]["situacao"] == "I"
