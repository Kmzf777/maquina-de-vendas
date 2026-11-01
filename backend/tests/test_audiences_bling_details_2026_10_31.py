import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.audiences import bling_details
from app.audiences.source import Store
from app.audiences.types import Detalhe, Fatos

AGORA = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, cache=None):
        self.cache = dict(cache or {})
        self.salvos: list[list[dict]] = []

    def detalhes(self, chaves):
        return {k: v for k, v in self.cache.items() if k in set(chaves)}

    def salvar_detalhes(self, rows):
        self.salvos.append(list(rows))


class FakeClient:
    def __init__(self, conta, contatos, chamadas):
        self.conta = conta
        self.contatos = contatos
        self.chamadas = chamadas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, path, params=None):
        self.chamadas.append((self.conta, path))
        cid = int(path.rsplit("/", 1)[1])
        v = self.contatos[(self.conta, cid)]
        if isinstance(v, Exception):
            raise v
        return {"data": v}

    async def post(self, *a, **k):
        pytest.fail("o Bling é só leitura: post não pode ser chamado")

    async def put(self, *a, **k):
        pytest.fail("o Bling é só leitura: put não pode ser chamado")

    async def delete(self, *a, **k):
        pytest.fail("o Bling é só leitura: delete não pode ser chamado")

    async def request(self, *a, **k):
        pytest.fail("use só get")


def _factory(contatos, chamadas):
    return lambda conta: FakeClient(conta, contatos, chamadas)


def _contato(email="a@b.com", nf="", municipio="Uberlândia", uf="MG", cep="38.400-123"):
    return {"id": 1, "email": email, "emailNotaFiscal": nf,
            "endereco": {"geral": {"municipio": municipio, "uf": uf, "cep": cep}}}


def _run(chaves, store, contatos, chamadas, **kw):
    return asyncio.run(bling_details.atualizar_detalhes(
        chaves, store, agora=AGORA, client_factory=_factory(contatos, chamadas), **kw))


def test_detalhe_recente_nao_e_buscado():
    d = Detalhe(email="x@y.com")
    store = FakeStore({("principal", 1): (d, AGORA - timedelta(days=5))})
    chamadas = []
    out = _run([("principal", 1)], store, {}, chamadas)
    assert chamadas == []
    assert out == {("principal", 1): d}
    assert store.salvos == []


def test_detalhe_com_31_dias_e_buscado_de_novo():
    store = FakeStore({("principal", 1): (Detalhe(email="velho@y.com"), AGORA - timedelta(days=31))})
    chamadas = []
    out = _run([("principal", 1)], store, {("principal", 1): _contato(email="novo@y.com")}, chamadas)
    assert chamadas == [("principal", "/contatos/1")]
    assert out[("principal", 1)] == Detalhe(email="novo@y.com", municipio="Uberlândia", uf="MG",
                                            cep="38.400-123")
    (rows,) = store.salvos
    assert rows == [{"account": "principal", "bling_contact_id": 1, "email": "novo@y.com",
                     "municipio": "Uberlândia", "uf": "MG", "cep": "38.400-123",
                     "buscado_em": AGORA.isoformat()}]


def test_sem_detalhe_e_buscado():
    chamadas = []
    out = _run([("secundaria", 7)], FakeStore(), {("secundaria", 7): _contato()}, chamadas)
    assert chamadas == [("secundaria", "/contatos/7")]
    assert out[("secundaria", 7)].email == "a@b.com"


def test_email_nota_fiscal_vira_fallback():
    out = _run([("principal", 2)], FakeStore(),
               {("principal", 2): _contato(email="  ", nf="nf@empresa.com")}, [])
    assert out[("principal", 2)].email == "nf@empresa.com"


def test_campos_vazios_viram_none():
    out = _run([("principal", 2)], FakeStore(),
               {("principal", 2): {"id": 2, "email": "", "endereco": {}}}, [])
    assert out[("principal", 2)] == Detalhe()


def test_erro_num_contato_nao_derruba_os_outros(caplog):
    store = FakeStore()
    contatos = {("principal", 1): RuntimeError("boom"), ("principal", 2): _contato(email="ok@x.com")}
    out = _run([("principal", 1), ("principal", 2)], store, contatos, [])
    assert ("principal", 1) not in out
    assert out[("principal", 2)].email == "ok@x.com"
    (rows,) = store.salvos
    assert [r["bling_contact_id"] for r in rows] == [2]
    assert "boom" in caplog.text


def test_um_client_por_conta_e_chaves_repetidas_uma_vez():
    criados = []
    contatos = {("principal", 1): _contato(), ("secundaria", 1): _contato(email="s@x.com")}
    chamadas = []

    def factory(conta):
        criados.append(conta)
        return FakeClient(conta, contatos, chamadas)

    out = asyncio.run(bling_details.atualizar_detalhes(
        [("principal", 1), ("secundaria", 1), ("principal", 1)], FakeStore(), agora=AGORA,
        client_factory=factory))
    assert sorted(criados) == ["principal", "secundaria"]
    assert len(chamadas) == 2
    assert out[("secundaria", 1)].email == "s@x.com"


def test_mapa_completo_cache_mais_novos():
    d = Detalhe(email="cache@x.com")
    store = FakeStore({("principal", 1): (d, AGORA)})
    out = _run([("principal", 1), ("principal", 2)], store, {("principal", 2): _contato()}, [])
    assert set(out) == {("principal", 1), ("principal", 2)}


# ---------- Store com um sb fake ----------

class _Q:
    def __init__(self, sb, table):
        self.sb, self.table, self.ops = sb, table, []

    def __getattr__(self, name):
        def f(*a, **k):
            self.ops.append((name, a, k))
            return self
        return f

    def execute(self):
        self.sb.queries.append((self.table, self.ops))
        return type("R", (), {"data": self.sb.responder(self.table, self.ops)})()


class FakeSb:
    def __init__(self, responder=lambda t, ops: []):
        self.queries = []
        self.responder = responder

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params=None):
        return _Q(self, f"rpc:{name}")


FATO = {"lead_id": "L1", "ultima_compra": "2026-10-01T00:00:00+00:00", "receita_365": "10.5",
        "nome": "Ana", "lead_phone": None, "lead_email": None,
        "contatos_bling": [{"account": "principal", "id": 3}]}


@pytest.mark.parametrize("data", [[FATO], json.dumps([FATO])])
def test_store_fatos_aceita_lista_ou_string(data):
    st = Store(sb=FakeSb(lambda t, ops: data))
    (f,) = st.fatos()
    assert isinstance(f, Fatos) and f.receita_365 == 10.5 and f.contatos_bling == [("principal", 3)]


def test_store_detalhes_em_pedacos_de_200_por_conta():
    def resp(t, ops):
        ids = next(a[1] for n, a, k in ops if n == "in_")
        conta = next(a[1] for n, a, k in ops if n == "eq")
        return [{"account": conta, "bling_contact_id": i, "email": None, "municipio": None,
                 "uf": None, "cep": "38400123", "buscado_em": "2026-10-30T00:00:00+00:00"} for i in ids]
    sb = FakeSb(resp)
    chaves = [("principal", i) for i in range(250)] + [("secundaria", 1)]
    out = Store(sb=sb).detalhes(chaves)
    assert len(sb.queries) == 3
    assert len(out) == 251
    d, quando = out[("principal", 5)]
    assert d.cep == "38400123" and quando.tzinfo is not None


def test_store_upsert_membros_nao_manda_primeiro_envio():
    sb = FakeSb()
    Store(sb=sb).upsert_membros("google_pl", [{"ident_hash": "h", "ident": {"emailAddress": "x"},
                                               "lead_id": "L1", "ultimo_envio": "t"}])
    (table, ops), = sb.queries
    name, a, k = next(o for o in ops if o[0] == "upsert")
    assert table == "audience_sync_members" and k["on_conflict"] == "audience_key,ident_hash"
    (row,) = a[0]
    assert row["audience_key"] == "google_pl" and row["removido_em"] is None
    assert "primeiro_envio" not in row


def test_store_rodada_automatica_desde():
    sb = FakeSb(lambda t, ops: [{"id": 1}])
    assert Store(sb=sb).rodada_automatica_desde("2026-10-31T04:00:00+00:00") is True
    (_t, ops), = sb.queries
    filtros = {(n, a) for n, a, k in ops if n in ("eq", "gte")}
    assert ("eq", ("trigger", "automatica")) in filtros
    assert ("eq", ("dry_run", False)) in filtros
    assert ("gte", ("iniciado_em", "2026-10-31T04:00:00+00:00")) in filtros
    assert Store(sb=FakeSb()).rodada_automatica_desde("x") is False


def test_store_marcar_removidos_em_pedacos():
    sb = FakeSb()
    Store(sb=sb).marcar_removidos("google_pl", [f"h{i}" for i in range(201)], "2026-10-31T04:00:00Z")
    assert len(sb.queries) == 2
    _t, ops = sb.queries[0]
    assert ("update", ({"removido_em": "2026-10-31T04:00:00Z"},), {}) in ops
