"""Router da jornada (F5): detalhe de campanha com `atribuicao`, só para admin."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.campaigns import jornada_router
from app.campaigns.traffic_router import exigir_admin


def _cliente(monkeypatch, admin=True):
    app = FastAPI()
    app.include_router(jornada_router.router)
    if admin:
        app.dependency_overrides[exigir_admin] = lambda: "admin@x"
    chamadas = []
    monkeypatch.setattr(jornada_router, "campaign_detail", lambda **kw: chamadas.append(kw) or {"ok": True})
    return TestClient(app), chamadas


def test_sem_token_401(monkeypatch):
    c, chamadas = _cliente(monkeypatch, admin=False)
    r = c.get("/api/traffic/jornada/campaign", params={"channel": "Meta Ads", "campaign": "x"})
    assert r.status_code == 401 and chamadas == []


def test_repassa_a_atribuicao(monkeypatch):
    c, chamadas = _cliente(monkeypatch)
    r = c.get("/api/traffic/jornada/campaign", params={"channel": "Meta Ads", "campaign": "x",
                                                       "atribuicao": "primeira", "period": "7d"})
    assert r.status_code == 200
    assert chamadas[0]["atribuicao"] == "primeira" and chamadas[0]["mode"] == "periodo"
    assert chamadas[0]["period"] == "7d"


def test_valores_invalidos_viram_padrao(monkeypatch):
    c, chamadas = _cliente(monkeypatch)
    c.get("/api/traffic/jornada/campaign", params={"channel": "a", "campaign": "b", "atribuicao": "x",
                                                   "mode": "y"})
    assert chamadas[0]["atribuicao"] == "ultima" and chamadas[0]["mode"] == "periodo"


def test_router_registrado_no_app():
    # url_path_for, não app.routes: do FastAPI 0.16x em diante (o do CI e da imagem) os routers
    # incluídos ficam como _IncludedRouter e as rotas não aparecem achatadas em app.routes.
    from app.main import app
    assert app.url_path_for("jornada_campaign_endpoint") == "/api/traffic/jornada/campaign"
