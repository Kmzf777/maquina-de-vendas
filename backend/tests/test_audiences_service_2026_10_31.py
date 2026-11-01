"""Serviço da sincronização de públicos: orquestração, lock e tick (cartão 4e0494e0). Sem rede."""
from datetime import datetime, timedelta, timezone

import pytest

from app.audiences import diff, google as google_real, meta as meta_real, service
from app.audiences.types import Detalhe, Fatos

AGORA = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _fato(lead_id, **kw):
    base = dict(lead_id=lead_id, ultima_compra=AGORA - timedelta(days=10), receita_365=100.0,
                nome="Maria Silva", lead_phone="+5534991234567", lead_email=f"{lead_id}@x.com")
    base.update(kw)
    return Fatos(**base)


class FakeStore:
    def __init__(self, fatos=None, ativos=None, rodada=False, falha_run=False):
        self._fatos = list(fatos or [])
        self.ativos = {k: dict(v) for k, v in (ativos or {}).items()}
        self.rodada = rodada
        self.falha_run = falha_run
        self.runs: list[dict] = []
        self.upserts: list[tuple[str, list[dict]]] = []
        self.removidos: list[tuple[str, set, str]] = []
        self.inicios: list[str] = []

    def fatos(self):
        return list(self._fatos)

    def detalhes(self, chaves):
        return {}

    def salvar_detalhes(self, rows):
        pass

    def membros_ativos(self, key):
        return dict(self.ativos.get(key, {}))

    def upsert_membros(self, key, rows):
        self.upserts.append((key, list(rows)))

    def marcar_removidos(self, key, hashes, quando_iso):
        self.removidos.append((key, set(hashes), quando_iso))

    def registrar_run(self, row):
        if self.falha_run:
            raise RuntimeError("banco fora")
        self.runs.append(row)

    def rodada_automatica_desde(self, inicio_iso):
        self.inicios.append(inicio_iso)
        return self.rodada


class FakeRedis:
    def __init__(self, ocupado=False):
        self.data = {"audience_sync:lock": "outro"} if ocupado else {}
        self.sets = []

    async def set(self, key, value, nx=False, ex=None):
        self.sets.append((key, value, nx, ex))
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


class FakeMeta:
    build_rows = staticmethod(meta_real.build_rows)

    def __init__(self, falha=False):
        self.falha = falha
        self.replaces = []
        self.checks = []

    def replace(self, audience_id, pessoas, **kw):
        if self.falha:
            raise RuntimeError("Meta caiu")
        pessoas = list(pessoas)
        self.replaces.append((audience_id, pessoas))
        return {"num_received": len(pessoas), "num_invalid_entries": 0, "session_id": 1,
                "lotes": 1, "linhas": len(pessoas), "respostas": []}

    def check_audience(self, audience_id, **kw):
        if self.falha:
            raise RuntimeError("Meta caiu")
        self.checks.append(audience_id)
        return {"id": audience_id, "name": "x"}


class FakeGoogle:
    build_member = staticmethod(google_real.build_member)
    remove_member = staticmethod(google_real.remove_member)
    identificadores = staticmethod(google_real.identificadores)

    def __init__(self):
        self.ingests = []
        self.removes = []

    def ingest(self, audience_id, members, *, validate_only):
        self.ingests.append((audience_id, list(members), validate_only))
        return [{"requestId": "i1"}]

    def remove(self, audience_id, members, *, validate_only):
        self.removes.append((audience_id, list(members), validate_only))
        return [{"requestId": "r1"}]


async def fake_bling(chaves, store, *, agora, client_factory=None):
    return {}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "1234567890")


async def _run(store, *, dry_run=False, redis=None, meta=None, google=None):
    return await service.run(trigger="manual", dry_run=dry_run, store=store,
                             redis=redis or FakeRedis(), agora=AGORA,
                             meta_mod=meta or FakeMeta(), google_mod=google or FakeGoogle(),
                             bling=fake_bling)


async def test_falha_no_meta_nao_impede_google_e_grava_4_runs():
    store = FakeStore([_fato("a", pipeline_pl=True, pipeline_atacado=True)])
    g = FakeGoogle()
    res = await _run(store, meta=FakeMeta(falha=True), google=g)
    assert len(store.runs) == 4
    por_key = {r["audience_key"]: r for r in store.runs}
    assert "Meta caiu" in por_key["meta_pl"]["erro"]
    assert "Meta caiu" in por_key["meta_atacado"]["erro"]
    assert por_key["google_pl"]["erro"] is None
    assert len(g.ingests) == 2
    assert res["por_publico"]["meta_pl"]["erro"]
    for r in store.runs:
        assert r["trigger"] == "manual" and r["dry_run"] is False and r["run_id"] == res["run_id"]
        assert r["iniciado_em"] and r["terminado_em"]


async def test_falha_no_registrar_run_nao_derruba():
    store = FakeStore([_fato("a", pipeline_pl=True)], falha_run=True)
    res = await _run(store)
    assert "contagem" in res


async def test_lock_ocupado_nao_envia_nada():
    store = FakeStore([_fato("a", pipeline_pl=True)])
    m, g = FakeMeta(), FakeGoogle()
    res = await _run(store, redis=FakeRedis(ocupado=True), meta=m, google=g)
    assert res == {"status": "lock"}
    assert not m.replaces and not m.checks and not g.ingests and not store.runs


async def test_lock_e_liberado_so_se_ainda_for_meu():
    r = FakeRedis()
    await _run(FakeStore([_fato("a", pipeline_pl=True)]), redis=r)
    assert r.sets[0][0] == "audience_sync:lock" and r.sets[0][2] is True and r.sets[0][3] == 3600
    assert "audience_sync:lock" not in r.data

    class Roubado(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            ok = await super().set(key, value, nx=nx, ex=ex)
            self.data[key] = "outro-run"
            return ok
    r2 = Roubado()
    await _run(FakeStore([_fato("a", pipeline_pl=True)]), redis=r2)
    assert r2.data["audience_sync:lock"] == "outro-run"


async def test_dry_run_meta_so_check_google_validate_only_sem_gravar():
    sai = {"emailAddress": "velho"}
    store = FakeStore([_fato("a", pipeline_pl=True)],
                      ativos={"google_pl": {diff.ident_hash(sai): sai}})
    m, g = FakeMeta(), FakeGoogle()
    await _run(store, dry_run=True, meta=m, google=g)
    assert not m.replaces
    assert set(m.checks) == {"120252789539440163", "120252789580640163"}
    assert g.ingests and all(v is True for _, _, v in g.ingests)
    assert g.removes and all(v is True for _, _, v in g.removes)
    assert not store.upserts and not store.removidos
    meta_pl = next(r for r in store.runs if r["audience_key"] == "meta_pl")
    assert meta_pl["linhas_enviadas"] == 1 and meta_pl["api_response"] == {"id": "120252789539440163", "name": "x"}
    assert all(r["dry_run"] is True for r in store.runs)


async def test_quem_saiu_e_removido_no_google_e_marcado():
    sai = {"emailAddress": "velho"}
    h_sai = diff.ident_hash(sai)
    store = FakeStore([_fato("a", pipeline_pl=True)], ativos={"google_pl": {h_sai: sai}})
    g = FakeGoogle()
    await _run(store, google=g)
    rem = [x for x in g.removes if x[0] == "9496018532"]
    assert rem == [("9496018532", [google_real.remove_member(sai)], False)]
    assert [(k, h) for k, h, _ in store.removidos] == [("google_pl", {h_sai})]
    up = dict(store.upserts)["google_pl"]
    assert {r["lead_id"] for r in up} == {"a"}
    assert all(r["ident_hash"] == diff.ident_hash(r["ident"]) and r["ultimo_envio"] for r in up)
    run = next(r for r in store.runs if r["audience_key"] == "google_pl")
    assert run["removidos"] == 1 and run["pessoas"] == 1
    # atacado não tem ninguém: não chama ingest
    assert not [x for x in g.ingests if x[0] == "9496602202"]


async def test_meta_real_usa_replace_com_pessoas_do_segmento():
    store = FakeStore([_fato("a", pipeline_pl=True), _fato("b", pipeline_atacado=True)])
    m = FakeMeta()
    await _run(store, meta=m)
    por_id = {aid: [p.lead_id for p in ps] for aid, ps in m.replaces}
    assert por_id == {"120252789539440163": ["a"], "120252789580640163": ["b"]}


async def test_contagem_do_resumo():
    fatos = [
        _fato("pl", tag_pl=True),
        _fato("at", tag_atacado=True),
        _fato("dois", tag_pl=True, segmento="atacado"),
        _fato("cnpj", docs=["12345678000199"]),
        _fato("fora", docs=["12345678901"]),
        _fato("velho", tag_pl=True, ultima_compra=AGORA - timedelta(days=400)),
    ]
    res = await _run(FakeStore(fatos))
    assert res["contagem"] == {"total": 5, "pl": 2, "atacado": 3, "dois": 1, "fora": 1,
                               "cnpj_sem_classe": 1}
    meta_at = res["por_publico"]["meta_atacado"]
    assert meta_at["pessoas"] == 3 and meta_at["com_celular"] == 3 and meta_at["com_email"] == 3


# ---- tick ----

SP = timezone(timedelta(hours=-3))


class Runner:
    def __init__(self):
        self.chamadas = []

    async def __call__(self, **kw):
        self.chamadas.append(kw)
        return {}


async def test_tick_antes_da_uma_nao_roda(monkeypatch):
    monkeypatch.setenv("AUDIENCE_SYNC_ENABLED", "true")
    r, store = Runner(), FakeStore()
    await service.tick(agora=datetime(2026, 10, 31, 0, 50, tzinfo=SP), store=store, runner=r)
    assert not r.chamadas and not store.inicios


async def test_tick_0105_sem_rodada_roda(monkeypatch):
    monkeypatch.setenv("AUDIENCE_SYNC_ENABLED", "1")
    r, store = Runner(), FakeStore()
    await service.tick(agora=datetime(2026, 10, 31, 1, 5, tzinfo=SP), store=store, runner=r)
    assert store.inicios == ["2026-10-31T04:00:00+00:00"]
    assert len(r.chamadas) == 1
    assert r.chamadas[0]["trigger"] == "automatica" and r.chamadas[0]["dry_run"] is False


async def test_tick_com_rodada_hoje_nao_roda(monkeypatch):
    monkeypatch.setenv("AUDIENCE_SYNC_ENABLED", "on")
    r = Runner()
    await service.tick(agora=datetime(2026, 10, 31, 9, 0, tzinfo=SP), store=FakeStore(rodada=True),
                       runner=r)
    assert not r.chamadas


async def test_tick_desligado_nao_roda(monkeypatch):
    monkeypatch.delenv("AUDIENCE_SYNC_ENABLED", raising=False)
    r, store = Runner(), FakeStore()
    await service.tick(agora=datetime(2026, 10, 31, 9, 0, tzinfo=SP), store=store, runner=r)
    assert not r.chamadas and not store.inicios


def test_worker_registra_audience_sync():
    from app.worker import main
    spec = next(s for s in main.TASK_SPECS if s[0] == "audience-sync")
    assert spec[1] == "periodic" and spec[3] == 600


async def test_google_pula_pessoa_sem_identificador():
    # Membro sem userIdentifiers faz a Data Manager recusar o lote inteiro.
    store = FakeStore([_fato("a", pipeline_pl=True),
                       _fato("b", pipeline_pl=True, lead_phone=None, lead_email=None)])
    g = FakeGoogle()
    await _run(store, google=g)
    (_, membros, _), = [x for x in g.ingests if x[0] == "9496018532"]
    assert len(membros) == 1 and all(m["userData"]["userIdentifiers"] for m in membros)
    run = next(r for r in store.runs if r["audience_key"] == "google_pl")
    assert run["pessoas"] == 2 and run["linhas_enviadas"] == 1
