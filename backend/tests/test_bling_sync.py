import asyncio

import app.bling.sync as sync


class FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upsert(self, rows, on_conflict=None):
        self.store.setdefault(self.name, []).extend(rows)
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
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
    def __init__(self, por_path):
        self.por_path = por_path
        self.params = {}

    async def paginate(self, path, params=None, limite=100):
        self.params[path] = params
        for item in self.por_path.get(path, []):
            yield item


def test_contato_normaliza_telefone_com_a_funcao_do_crm():
    """O casamento lead <-> contato depende de a normalizacao ser a MESMA dos dois
    lados. O Bling guarda '(51) 99269-6163'; leads.phone guarda '5551992696163'."""
    bruto = {
        "id": 5845664414, "nome": "360 IMP E DISTRIBUIDORA LTDA",
        "fantasia": "360 ALIMENTOS", "tipo": "J",
        "numeroDocumento": "29.860.598/0001-70",
        "telefone": "(51) 99269-6163", "celular": "51 3714-1000",
        "email": "adm@projetos360.com.br", "situacao": "A",
    }
    row = sync.map_contact(bruto)
    assert row["doc_digits"] == "29860598000170"
    assert row["telefone_e164"] == "5551992696163"
    assert row["celular_e164"] == "555137141000"
    assert row["email"] == "adm@projetos360.com.br"


def test_contato_sem_documento_fica_com_doc_digits_nulo():
    row = sync.map_contact({"id": 1, "nome": "X", "tipo": "F"})
    assert row["doc_digits"] is None


def test_contato_extrai_endereco_para_jsonb():
    bruto = {
        "id": 2, "nome": "Y", "tipo": "J",
        "endereco": {"geral": {"endereco": "Rua A", "numero": "255", "bairro": "Centro",
                               "municipio": "Uberlandia", "uf": "MG", "cep": "38400084"}},
    }
    row = sync.map_contact(bruto)
    assert row["endereco"]["municipio"] == "Uberlandia"
    assert row["endereco"]["cep"] == "38400084"


def test_sync_contacts_incremental_usa_data_alteracao(monkeypatch):
    store = {"row_bling_sync_state": {"last_sync_at": "2026-08-17T00:00:00+00:00"}}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    n = asyncio.run(sync.sync_contacts(client))

    assert n == 1
    assert client.params["/contatos"]["dataAlteracaoInicial"] == "2026-08-17T00:00:00+00:00"


def test_sync_contacts_completo_usa_criterio_1_todos(monkeypatch):
    """criterio=3 (default do Bling) traz so os 'ultimos incluidos' — no primeiro
    sync isso deixaria a base incompleta silenciosamente."""
    store = {}
    client = FakeClient({"/contatos": [{"id": 1, "nome": "A", "tipo": "J"}]})
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_contacts(client))

    assert client.params["/contatos"]["criterio"] == 1


def test_sync_payment_methods_e_sellers(monkeypatch):
    store = {}
    client = FakeClient({
        "/formas-pagamentos": [{"id": 45, "descricao": "Boleto", "tipoPagamento": 15,
                                "situacao": 1, "padrao": 1, "finalidade": 2}],
        "/vendedores": [{"id": 7, "contato": {"nome": "Joao Bras"}, "situacao": "A"}],
    })
    monkeypatch.setattr(sync, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(sync, "_save_sync_state", lambda *a, **k: None)

    asyncio.run(sync.sync_payment_methods(client))
    asyncio.run(sync.sync_sellers(client))

    assert store["bling_payment_methods"][0]["descricao"] == "Boleto"
    assert store["bling_sellers"][0]["nome"] == "Joao Bras"


def test_tick_nao_faz_nada_quando_desabilitado(monkeypatch):
    monkeypatch.setattr(sync.config, "enabled", lambda: False)
    chamou = []
    monkeypatch.setattr(sync, "sync_all", lambda *a, **k: chamou.append(True))
    asyncio.run(sync.bling_sync_tick())
    assert chamou == []


def test_worker_registra_o_tick_de_sync():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-sync")
    assert spec[1] == "periodic"
    assert callable(spec[2])
    assert spec[3] == 86400
