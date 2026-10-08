from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.campaigns import traffic_router

from app.conversions import router as router_mod
from app.conversions.router import summarize


def test_summarize_conta_por_etapa_plataforma_status():
    rows = [
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "purchase", "platform": "google", "status": "erro"},
    ]
    assert summarize(rows) == [
        {"stage": "purchase", "platform": "google", "status": "erro", "n": 1},
        {"stage": "qualified", "platform": "meta", "status": "enviado", "n": 2},
    ]


@pytest.fixture
def admin_app():
    from app.main import app
    app.dependency_overrides[traffic_router.exigir_admin] = lambda: "admin@x.com"
    yield app
    app.dependency_overrides.pop(traffic_router.exigir_admin, None)


class _Q:
    """Query builder falso: a lista (select com o join do lead) devolve `lista`; a contagem
    (select leve `stage,platform,status`) devolve `todas` fatiada pelo `.range()`."""

    def __init__(self, lista, todas, log):
        self.lista, self.todas, self.log = lista, todas, log
        self.sel = None
        self.rng = None

    def select(self, cols):
        self.sel = cols
        self.log.append(("select", cols))
        return self

    def range(self, a, b):
        self.rng = (a, b)
        self.log.append(("range", (a, b)))
        return self

    def __getattr__(self, n):
        def call(*a, **k):
            self.log.append((n, a))
            return self
        return call

    def execute(self):
        if self.sel == "stage,platform,status":
            a, b = self.rng
            return MagicMock(data=self.todas[a:b + 1])
        return MagicMock(data=self.lista)


def _sb(lista, todas, log):
    sb = MagicMock()
    sb.table.side_effect = lambda n: _Q(lista, todas, log)
    return sb


def test_endpoint(monkeypatch, admin_app):
    lista = [{"id": "R1", "stage": "lead", "platform": "meta", "status": "enviado", "lead": {"name": "Ana"}}]
    monkeypatch.setattr(router_mod, "get_supabase",
                        lambda: _sb(lista, [{"stage": "lead", "platform": "meta", "status": "enviado"}], []))
    r = TestClient(admin_app).get("/api/conversions/ads?period=30d")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["lead"]["name"] == "Ana"
    assert body["counts"] == [{"stage": "lead", "platform": "meta", "status": "enviado", "n": 1}]
    assert body["truncated"] is False


def test_range_datas_em_sao_paulo_fim_exclusivo():
    ini, fim = router_mod._range("30d", "2026-10-01", "2026-10-07")
    assert ini.startswith("2026-10-01T00:00:00-03:00")
    assert fim.startswith("2026-10-08T00:00:00-03:00")


def test_contadores_contam_todas_as_linhas_mesmo_com_a_lista_truncada(monkeypatch, admin_app):
    """A lista para em 1000 (teto do PostgREST), mas os contadores das abas somam TODAS as
    linhas do filtro — paginadas num select leve."""
    lista = [{"id": f"R{i}", "stage": "qualified", "platform": "meta", "status": "enviado", "lead": None}
             for i in range(1000)]
    todas = ([{"stage": "qualified", "platform": "meta", "status": "enviado"}] * 2300
             + [{"stage": "purchase", "platform": "google", "status": "erro"}] * 200)
    log = []
    monkeypatch.setattr(router_mod, "get_supabase", lambda: _sb(lista, todas, log))
    r = TestClient(admin_app).get("/api/conversions/ads?period=30d&platform=meta")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 1000 and body["truncated"] is True
    assert body["counts"] == [
        {"stage": "purchase", "platform": "google", "status": "erro", "n": 200},
        {"stage": "qualified", "platform": "meta", "status": "enviado", "n": 2300},
    ]
    assert [a for n, a in log if n == "range"] == [(0, 999), (1000, 1999), (2000, 2999)]
    # mesma filtragem na contagem e na lista; contagem paginada em ordem estável
    assert log.count(("eq", ("platform", "meta"))) == 4  # 1 da lista + 3 páginas
    assert ("order", ("id",)) in log


def test_endpoint_exige_admin(monkeypatch):
    monkeypatch.setattr(router_mod, "get_supabase", lambda: _sb([], [], []))
    from app.main import app
    assert TestClient(app).get("/api/conversions/ads").status_code == 401


def test_endpoint_recusa_quem_nao_e_admin(monkeypatch):
    import time as _t

    import jwt as pyjwt

    from app.config import settings

    segredo = "segredo-de-teste-com-32-caracteres!!"
    monkeypatch.setattr(settings, "supabase_jwt_secret", segredo)
    monkeypatch.setattr(router_mod, "get_supabase", lambda: _sb([], [], []))

    def tok(role):
        return pyjwt.encode({"aud": "authenticated", "exp": int(_t.time()) + 3600, "sub": "u1",
                             "email": f"{role}@x.com", "app_metadata": {"role": role}}, segredo, algorithm="HS256")

    from app.main import app
    c = TestClient(app)
    r = c.get("/api/conversions/ads", headers={"Authorization": f"Bearer {tok('vendedor')}"})
    assert r.status_code == 403
    r = c.get("/api/conversions/ads", headers={"Authorization": f"Bearer {tok('admin')}"})
    assert r.status_code == 200
