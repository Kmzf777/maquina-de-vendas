"""Frente F1 (06/11/2026): /trafego seguro e confiável.

- Login de admin em todas as rotas de tráfego (o /leads devolvia nome e telefone sem login).
- Modo padrão "sale" (por venda) no router.
- Falha do sync de investimento: rodada gravada com o motivo, system_alert com dedup de 12 h por
  plataforma e 0 linhas suspeitas (dia útil com gasto recente) como aviso.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.campaigns.ad_spend_sync as s
import app.campaigns.traffic_router as rotas
from app.campaigns.google_ads import AdsFetchError


# ── banco falso: guarda inserts e responde selects com filtros simples ───────────────────────

class _Q:
    def __init__(self, banco, nome):
        self.banco, self.nome, self.filtros, self._insert = banco, nome, [], None

    def select(self, *_a, **_k):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def upsert(self, rows, on_conflict=None):
        self.banco.tabelas.setdefault(self.nome, []).extend(rows)
        return self

    def eq(self, col, val):
        self.filtros.append(("eq", col, val))
        return self

    def gt(self, col, val):
        self.filtros.append(("gt", col, val))
        return self

    def gte(self, col, val):
        self.filtros.append(("gte", col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def _casa(self, row):
        for op, col, val in self.filtros:
            if col.startswith("metadata->>"):
                atual = (row.get("metadata") or {}).get(col.split("->>")[1])
            else:
                atual = row.get(col)
            if op == "eq" and atual != val:
                return False
            if op == "gt" and not (atual is not None and atual > val):
                return False
            if op == "gte" and not (atual is not None and str(atual) >= str(val)):
                return False
        return True

    def execute(self):
        tabela = self.banco.tabelas.setdefault(self.nome, [])
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            row.setdefault("criado_em", datetime.now(timezone.utc).isoformat())
            row.setdefault("resolved", False)
            tabela.append(row)
            return type("R", (), {"data": [row]})()
        return type("R", (), {"data": [r for r in tabela if self._casa(r)]})()


class _Banco:
    def __init__(self, **tabelas):
        self.tabelas = {k: list(v) for k, v in tabelas.items()}

    def table(self, nome):
        return _Q(self, nome)


@pytest.fixture
def banco(monkeypatch):
    b = _Banco(system_alerts=[], ad_spend_sync_runs=[], ad_spend=[])
    monkeypatch.setattr(s, "get_supabase", lambda: b)
    import app.alerts.service as alerts
    monkeypatch.setattr(alerts, "get_supabase", lambda: b)
    monkeypatch.setattr(alerts, "_notify_external", lambda *a, **k: None)
    return b


# ── 1. login ──────────────────────────────────────────────────────────────────────────────

def _cliente(admin: bool):
    app = FastAPI()
    app.include_router(rotas.router)
    if admin:
        app.dependency_overrides[rotas.exigir_admin] = lambda: "admin@x.com"
    return TestClient(app)


@pytest.fixture
def relatorio_falso(monkeypatch):
    chamadas = {}

    def report(period, mode, date_from=None, date_to=None):
        chamadas["report"] = mode
        return {"mode": mode}

    def leads(channel, campaign, period, mode, date_from=None, date_to=None):
        chamadas["leads"] = mode
        return [{"name": "Fulano", "phone": "5534999999999"}]

    def detail(channel, campaign, period, mode, date_from=None, date_to=None):
        chamadas["campaign"] = mode
        return {"summary": {}}

    async def sync(days=30, origem="automatica"):
        chamadas["sync"] = origem
        return {"google": 1, "meta": 0, "errors": {}, "avisos": {}}

    monkeypatch.setattr(rotas, "traffic_report", report)
    monkeypatch.setattr(rotas, "campaign_leads", leads)
    monkeypatch.setattr(rotas, "campaign_detail", detail)
    monkeypatch.setattr(rotas, "sync_all_ad_spend", sync)
    monkeypatch.setattr(rotas, "ultimas_rodadas", lambda: {})
    return chamadas


_ROTAS = [
    ("get", "/api/traffic/report"),
    ("get", "/api/traffic/leads?channel=Meta%20Ads&campaign=X"),
    ("get", "/api/traffic/campaign?channel=Meta%20Ads&campaign=X"),
    ("post", "/api/traffic/sync-ads"),
    ("get", "/api/traffic/sync-status"),
]


@pytest.mark.parametrize("metodo,url", _ROTAS)
def test_rota_sem_token_responde_401(relatorio_falso, metodo, url):
    r = getattr(_cliente(admin=False), metodo)(url)
    assert r.status_code == 401
    assert "sync" not in relatorio_falso  # o sync não roda sem login


@pytest.mark.parametrize("metodo,url", _ROTAS)
def test_rota_com_jwt_de_vendedor_responde_403(relatorio_falso, monkeypatch, metodo, url):
    import time as _t

    import jwt as pyjwt

    from app.config import settings

    segredo = "segredo-de-teste-com-32-caracteres!!"
    monkeypatch.setattr(settings, "supabase_jwt_secret", segredo)
    token = pyjwt.encode({"aud": "authenticated", "exp": int(_t.time()) + 3600,
                          "sub": "00000000-0000-4000-8000-000000000002",
                          "email": "vendedor@cafecanastra.com",
                          "app_metadata": {"role": "vendedor"}, "role": "authenticated"},
                         segredo, algorithm="HS256")
    r = getattr(_cliente(admin=False), metodo)(url, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.parametrize("metodo,url", _ROTAS)
def test_rota_com_admin_responde_200(relatorio_falso, metodo, url):
    assert getattr(_cliente(admin=True), metodo)(url).status_code == 200


# ── 2. modo padrão "sale" ─────────────────────────────────────────────────────────────────

def test_modo_padrao_e_por_venda_nos_tres_endpoints(relatorio_falso):
    c = _cliente(admin=True)
    c.get("/api/traffic/report")
    c.get("/api/traffic/leads?channel=Meta%20Ads&campaign=X")
    c.get("/api/traffic/campaign?channel=Meta%20Ads&campaign=X")
    assert relatorio_falso["report"] == relatorio_falso["leads"] == relatorio_falso["campaign"] == "sale"


def test_modo_invalido_cai_em_venda_e_lead_explicito_e_respeitado(relatorio_falso):
    c = _cliente(admin=True)
    c.get("/api/traffic/report?mode=xpto")
    assert relatorio_falso["report"] == "sale"
    c.get("/api/traffic/report?mode=lead")
    assert relatorio_falso["report"] == "lead"


def test_sync_pela_tela_grava_origem_manual(relatorio_falso):
    r = _cliente(admin=True).post("/api/traffic/sync-ads")
    assert r.json()["synced"] == 1 and relatorio_falso["sync"] == "manual"


# ── 4. falha do sync: rodada gravada, alerta com dedup, zero suspeito ─────────────────────

def _google_ligado_meta_desligado(monkeypatch):
    monkeypatch.setattr(s, "google_ads_enabled", lambda: True)
    monkeypatch.setattr(s, "meta_ads_enabled", lambda: False)


def test_tick_com_ads_fetch_error_grava_rodada_e_alerta_uma_vez_em_12h(banco, monkeypatch):
    _google_ligado_meta_desligado(monkeypatch)

    async def boom(a, b):
        raise AdsFetchError("HTTP 404 em v22 — versão da API provavelmente descontinuada")
    monkeypatch.setattr(s, "fetch_campaign_spend", boom)

    from app.worker.main import _ad_spend_sync_tick
    asyncio.run(_ad_spend_sync_tick())

    rodadas = banco.tabelas["ad_spend_sync_runs"]
    assert len(rodadas) == 1
    assert rodadas[0]["platform"] == "google" and rodadas[0]["status"] == "falha"
    assert "404" in rodadas[0]["motivo"] and rodadas[0]["origem"] == "automatica"
    alertas = banco.tabelas["system_alerts"]
    assert len(alertas) == 1
    a = alertas[0]
    assert a["type"] == "ad_spend_sync_failed" and a["severity"] == "warning"
    assert a["metadata"]["plataforma"] == "google" and "404" in a["metadata"]["motivo"]

    # segunda falha dentro de 12 h: grava a rodada, mas não cria outro alerta
    asyncio.run(_ad_spend_sync_tick())
    assert len(banco.tabelas["ad_spend_sync_runs"]) == 2
    assert len(banco.tabelas["system_alerts"]) == 1


def test_alerta_antigo_mais_de_12h_nao_segura_o_novo(banco):
    velho = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    banco.tabelas["system_alerts"].append({"type": "ad_spend_sync_failed", "resolved": False,
                                           "created_at": velho, "metadata": {"plataforma": "google"}})
    assert s.alertar_falhas({"errors": {"google": "HTTP 500"}}) == ["google"]
    assert len(banco.tabelas["system_alerts"]) == 2


def test_dedup_e_por_plataforma(banco):
    assert s.alertar_falhas({"errors": {"google": "HTTP 500"}}) == ["google"]
    assert s.alertar_falhas({"errors": {"meta": "token expirado"}}) == ["meta"]
    assert s.alertar_falhas({"errors": {"google": "HTTP 500", "meta": "x"}}) == []


def test_sucesso_grava_rodada_ok_sem_alerta(banco, monkeypatch):
    _google_ligado_meta_desligado(monkeypatch)

    async def ok(a, b):
        return [{"campaign_id": "1", "campaign_name": "Atacado", "date": "2026-11-05", "cost": 10.0}]
    monkeypatch.setattr(s, "fetch_campaign_spend", ok)
    res = asyncio.run(s.sync_all_ad_spend(days=7))
    assert res["errors"] == {} and res["avisos"] == {}
    assert banco.tabelas["ad_spend_sync_runs"][0]["status"] == "ok"
    assert banco.tabelas["ad_spend_sync_runs"][0]["linhas"] == 1
    assert s.alertar_falhas(res) == [] and banco.tabelas["system_alerts"] == []


def test_zero_linhas_em_dia_util_com_gasto_recente_vira_aviso(banco, monkeypatch):
    _google_ligado_meta_desligado(monkeypatch)
    banco.tabelas["ad_spend"] = [{"platform": "google", "cost": 50.0, "date": "2026-11-03"}]

    async def vazio(a, b):
        return []
    monkeypatch.setattr(s, "fetch_campaign_spend", vazio)
    # "hoje" fixo numa quinta-feira, para o teste não depender do dia em que roda
    original = s._zero_suspeito
    monkeypatch.setattr(s, "_zero_suspeito", lambda p, hoje=None: original(p, date(2026, 11, 5)))
    res = asyncio.run(s.sync_all_ad_spend(days=7))
    assert "google" in res["avisos"] and res["errors"] == {}
    assert banco.tabelas["ad_spend_sync_runs"][0]["status"] == "aviso"
    assert s.alertar_falhas(res) == ["google"]
    assert banco.tabelas["system_alerts"][0]["metadata"]["tipo"] == "aviso"


def test_zero_linhas_no_fim_de_semana_ou_sem_gasto_recente_nao_e_aviso(banco):
    banco.tabelas["ad_spend"] = [{"platform": "google", "cost": 50.0, "date": "2026-11-06"}]
    assert s._zero_suspeito("google", date(2026, 11, 8)) is None  # domingo
    banco.tabelas["ad_spend"] = [{"platform": "google", "cost": 50.0, "date": "2026-10-01"}]
    assert s._zero_suspeito("google", date(2026, 11, 5)) is None  # sem gasto nos últimos 7 dias
    banco.tabelas["ad_spend"] = [{"platform": "google", "cost": 0, "date": "2026-11-04"}]
    assert s._zero_suspeito("google", date(2026, 11, 5)) is None  # gasto zero não conta


def test_plataforma_desligada_nao_grava_rodada(banco, monkeypatch):
    monkeypatch.setattr(s, "google_ads_enabled", lambda: False)
    monkeypatch.setattr(s, "meta_ads_enabled", lambda: False)
    asyncio.run(s.sync_all_ad_spend(days=7))
    assert banco.tabelas["ad_spend_sync_runs"] == []


def test_sem_tabela_de_rodadas_o_sync_segue(monkeypatch):
    """Migração ainda não aplicada: o sync não pode quebrar por causa do histórico."""
    class _Quebrado:
        def table(self, nome):
            raise RuntimeError("relation ad_spend_sync_runs does not exist")
    monkeypatch.setattr(s, "get_supabase", lambda: _Quebrado())
    s._registrar_rodada("google", "ok", 3, None, "manual")
    assert s.ultimas_rodadas() == {}


def test_ultimas_rodadas_devolve_a_mais_recente_de_cada_plataforma(banco):
    banco.tabelas["ad_spend_sync_runs"] = [
        {"platform": "google", "status": "falha", "linhas": 0, "motivo": "HTTP 404",
         "criado_em": "2026-11-06T12:00:00+00:00"},
        {"platform": "meta", "status": "ok", "linhas": 12, "motivo": None,
         "criado_em": "2026-11-06T12:00:01+00:00"},
    ]
    out = s.ultimas_rodadas()
    assert out["google"] == {"status": "falha", "linhas": 0, "motivo": "HTTP 404",
                             "em": "2026-11-06T12:00:00+00:00"}
    assert out["meta"]["status"] == "ok"
