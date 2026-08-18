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
