import asyncio

import app.bling.jobs as jobs
from app.bling.errors import BlingServerError, BlingValidationError


class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def lte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.store.setdefault(self.name + "_inserts", []).append(payload)
        return self

    def update(self, payload):
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


def test_enqueue_grava_job_pendente(monkeypatch):
    store = {}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    asyncio.run(jobs.enqueue("create_order", {"lead_id": "L1"}, sale_id="S1"))

    job = store["bling_jobs_inserts"][0]
    assert job["kind"] == "create_order"
    assert job["status"] == "pending"
    assert job["sale_id"] == "S1"


def test_enqueue_gera_chave_de_idempotencia(monkeypatch):
    """A chave nasce no enfileiramento e vai gravada no job — e ela que vira
    `numeroLoja` no Bling e impede o pedido de nascer duas vezes."""
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(jobs, "get_supabase", lambda: fake_db)

    original = {"lead_id": "L1"}
    asyncio.run(jobs.enqueue("create_order", original, sale_id="S1"))

    payload = store["bling_jobs_inserts"][0]["payload"]
    assert payload["idempotency_key"].startswith("crm-")
    assert payload["lead_id"] == "L1"
    assert "idempotency_key" not in original, "nao muta o dict do chamador"


def test_enqueue_preserva_chave_ja_existente(monkeypatch):
    """Reenfileirar um job que ja tem chave nao pode trocar a chave: seria o
    mesmo que gerar uma nova por tentativa."""
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(jobs, "get_supabase", lambda: fake_db)

    asyncio.run(jobs.enqueue("create_order",
                             {"lead_id": "L1", "idempotency_key": "crm-fixa"}))

    assert store["bling_jobs_inserts"][0]["payload"]["idempotency_key"] == "crm-fixa"


def test_chave_de_idempotencia_e_estavel_entre_tentativas(monkeypatch):
    """Duas tentativas do MESMO job precisam mandar a mesma chave. Se cada
    tentativa gerasse a sua, o `numeroLoja` mudaria e o Bling criaria um pedido
    novo a cada retentativa — o mecanismo nao protegeria nada."""
    store = {}
    fake_db = FakeSupabase(store)
    monkeypatch.setattr(jobs, "get_supabase", lambda: fake_db)

    # enfileira UMA vez: e aqui que a chave nasce
    asyncio.run(jobs.enqueue("create_order", {"lead_id": "L1"}, sale_id="S1"))
    payload_do_job = store["bling_jobs_inserts"][0]["payload"]

    chaves = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    async def fake_create_order(client, **kwargs):
        chaves.append(kwargs.get("idempotency_key"))
        return {"sale_id": "S1"}

    import app.bling.client as client_mod
    import app.bling.orders as orders_mod
    monkeypatch.setattr(client_mod, "BlingClient", FakeClient)
    monkeypatch.setattr(orders_mod, "create_order", fake_create_order)

    job = {"id": "J1", "kind": "create_order", "payload": payload_do_job}
    # duas tentativas leem a MESMA linha do banco
    asyncio.run(jobs._handle_create_order(payload_do_job, job))
    asyncio.run(jobs._handle_create_order(payload_do_job, job))

    assert chaves[0] is not None and chaves[0].startswith("crm-")
    assert chaves[0] == chaves[1], "as duas tentativas usam a MESMA chave"
    # a chave e parametro nomeado, nao dado do pedido
    assert "idempotency_key" in payload_do_job, "o pop nao pode esvaziar o job"


def test_drain_marca_done_no_sucesso(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {"lead_id": "L1"}, "attempts": 0}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        return {"ok": True}

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    assert store["bling_jobs_updates"][0]["status"] == "done"


def test_erro_transitorio_reagenda_com_backoff(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": 1}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    upd = store["bling_jobs_updates"][0]
    assert upd["status"] == "pending"
    assert upd["attempts"] == 2
    assert upd["run_after"] > ""


def test_erro_de_validacao_marca_failed_sem_retentar(monkeypatch):
    """Repetir um payload invalido nunca conserta e ainda queima orcamento."""
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": 0}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingValidationError("itens invalidos")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    upd = store["bling_jobs_updates"][0]
    assert upd["status"] == "failed"
    assert "itens invalidos" in upd["last_error"]


def test_desiste_apos_o_maximo_de_tentativas(monkeypatch):
    store = {"row_bling_jobs": [{"id": "J1", "kind": "create_order",
                                 "payload": {}, "attempts": jobs.MAX_ATTEMPTS - 1}]}
    monkeypatch.setattr(jobs, "get_supabase", lambda: FakeSupabase(store))

    async def handler(payload, job):
        raise BlingServerError("ainda fora")

    monkeypatch.setattr(jobs, "_HANDLERS", {"create_order": handler})

    asyncio.run(jobs.drain())

    assert store["bling_jobs_updates"][0]["status"] == "failed"


def test_worker_registra_o_drain():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-jobs")
    assert spec[1] == "periodic"
    assert spec[3] == 30
