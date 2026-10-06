"""P2 da call de Ads de 01/10 — relatório /trafego.

Spec: docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md (P2). Cobre o funil
cumulativo sem canceladas (2.1), a atribuição manual (2.2), os endpoints de atribuição (2.3)
e as colunas novas da tabela de leads da campanha (2.4).
"""
import pytest

import app.campaigns.traffic_report as tr


# --- Banco falso com filtro de verdade (eq/in_/gte/lte/range/limit/update/insert) ---------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, banco, tabela):
        self.banco, self.tabela = banco, tabela
        self.filtros, self.cols, self.op, self.payload = [], "*", "select", None
        self._range = self._limit = None

    def select(self, cols="*", **_):
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filtros.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vs = set(vals)
        self.filtros.append(lambda r: r.get(col) in vs)
        return self

    def gte(self, col, val):
        self.filtros.append(lambda r: str(r.get(col) or "") >= str(val))
        return self

    def lte(self, col, val):
        self.filtros.append(lambda r: str(r.get(col) or "") <= str(val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def update(self, patch):
        self.op, self.payload = "update", patch
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def execute(self):
        if self.tabela in self.banco.ausentes:
            raise Exception(f'relation "public.{self.tabela}" does not exist')
        linhas = self.banco.tabelas.setdefault(self.tabela, [])
        if self.op == "insert":
            if self.tabela in self.banco.falha_insert:
                raise Exception("insert falhou")
            linhas.append(dict(self.payload))
            return _Resp([self.payload])
        alvo = [r for r in linhas if all(f(r) for f in self.filtros)]
        if self.op == "update":
            for r in alvo:
                r.update(self.payload)
            return _Resp([dict(r) for r in alvo])
        for col in self.banco.colunas_ausentes.get(self.tabela, ()):
            if col in self.cols:
                raise Exception(f"column {self.tabela}.{col} does not exist")
        if self._range is not None:
            alvo = alvo[self._range[0]:self._range[1] + 1]
        if self._limit is not None:
            alvo = alvo[:self._limit]
        return _Resp([dict(r) for r in alvo])


class _Banco:
    def __init__(self, **tabelas):
        self.tabelas = tabelas
        self.ausentes: set[str] = set()
        self.colunas_ausentes: dict[str, list[str]] = {}
        self.falha_insert: set[str] = set()

    def table(self, nome):
        return _Query(self, nome)


@pytest.fixture(autouse=True)
def _flags_de_coluna(monkeypatch):
    """As flags de coluna são de processo: um teste que as desliga não vaza para o próximo."""
    monkeypatch.setattr(tr._MetaAdCol, "enabled", True)
    monkeypatch.setattr(tr._P0Col, "enabled", True)


# --- 2.1 Funil cumulativo + canceladas fora ----------------------------------------------

def _g(i, **kw):
    lead = {"id": f"l{i}", "gclid": f"g{i}", "utm_campaign": "black",
            "created_at": "2026-09-01T12:00:00+00:00"}
    lead.update(kw)
    return lead


def test_funil_cumulativo_cenario_da_call():
    # 30 leads, 20 conversaram, 4 chegaram ao closer, 10 compraram — 6 deles sem deal nem
    # conversa (pedido do Bling de quem já era cliente). Era o "4 closer e 10 clientes".
    leads = [_g(i) for i in range(30)]
    conversa = {f"l{i}" for i in range(20)}
    closer = {f"l{i}" for i in range(4)}
    vendas = {f"l{i}": {"count": 1, "value": 60.0} for i in [*range(4), *range(20, 26)]}
    report = tr.build_campaign_report(leads, conversa, closer, vendas, "lead", "30d")
    total = report["total"]
    assert total["leads"] == 30
    assert total["conversas"] == 26  # 20 que conversaram + 6 clientes que entraram comprando
    assert total["closer"] == 10
    assert total["clientes"] == 10
    s = tr.build_report_summary(report, leads, vendas)
    assert s["funnel"]["entraram_ja_clientes"] == 6
    assert s["funnel"]["taxa_cliente"] == 1.0


def test_funil_cumulativo_closer_conta_como_conversa():
    report = tr.build_campaign_report([_g(1)], set(), {"l1"}, {}, "lead", "30d")
    assert (report["total"]["conversas"], report["total"]["closer"]) == (1, 1)
    assert report["entraram_ja_clientes"] == 0


def test_relatorio_vazio_tem_entraram_ja_clientes_zero():
    assert tr._empty_report("lead", "30d")["summary"]["funnel"]["entraram_ja_clientes"] == 0


def test_sales_by_lead_ignora_venda_cancelada(monkeypatch):
    rows = [
        {"lead_id": "a", "value": 60, "sold_at": "2026-09-10T10:00:00+00:00", "status": "registrada"},
        {"lead_id": "a", "value": 60, "sold_at": "2026-09-10T10:00:15+00:00", "status": "cancelada"},
        {"lead_id": "b", "value": 90, "sold_at": "2026-09-11T10:00:00+00:00", "status": "cancelada"},
        {"lead_id": "c", "value": 30, "sold_at": "2026-09-12T10:00:00+00:00", "status": None},
    ]
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000: rows)
    out = tr._sales_by_lead(None, ["a", "b", "c"], None, None, "lead")
    assert out["a"]["count"] == 1 and out["a"]["value"] == 60.0
    assert "b" not in out
    assert out["c"]["count"] == 1


def test_traffic_report_venda_cancelada_nao_vira_cliente(monkeypatch):
    banco = _Banco(
        leads=[_g(1)],
        sales=[{"lead_id": "l1", "value": 60.0, "sold_at": "2026-09-02T12:00:00+00:00",
                "status": "cancelada"}],
    )
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = tr.traffic_report(period="all", mode="lead")
    assert out["total"]["leads"] == 1
    assert out["total"]["clientes"] == 0 and out["total"]["receita"] == 0.0


def test_modo_venda_nao_traz_lead_so_com_venda_cancelada(monkeypatch):
    banco = _Banco(
        leads=[_g(1), _g(2)],
        sales=[
            {"lead_id": "l1", "value": 60.0, "sold_at": "2026-09-02T12:00:00+00:00", "status": "cancelada"},
            {"lead_id": "l2", "value": 80.0, "sold_at": "2026-09-02T12:00:00+00:00", "status": "registrada"},
        ],
    )
    monkeypatch.setattr(tr, "get_supabase", lambda: banco)
    out = tr.traffic_report(period="all", mode="sale")
    assert out["total"]["leads"] == 1 and out["total"]["receita"] == 80.0


# --- 2.2 Atribuição manual ---------------------------------------------------------------

_META = [{"campaign_id": "cm_atac", "campaign_name": "Atacado WA", "cost": 500.0},
         {"campaign_id": "cm_terc", "campaign_name": "Terceirização WA", "cost": 300.0}]
_GOOGLE = [{"campaign_id": "cg_pmax", "campaign_name": "PMAX | Atacado", "cost": 200.0}]


def _manual(canal, cid, nome):
    return {"campanha_manual_canal": canal, "campanha_manual_id": cid, "campanha_manual_nome": nome}


def test_atribuicao_manual_vence_meta_ad_id():
    lead = {"id": "a", "ctwa_clid": "x", "meta_ad_id": "ad1", **_manual("meta", "cm_terc", "Terceirização WA")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Meta Ads": _META},
                                   campaign_id_by_lead={"a": "cm_atac"})
    rows = {r["campaign"]: r for r in rep["rows"]}
    assert rows["Terceirização WA"]["leads"] == 1
    assert rows["Atacado WA"]["leads"] == 0


def test_atribuicao_manual_troca_o_canal():
    lead = {"id": "a", "utm_source": "instagram", **_manual("google", "cg_pmax", "PMAX | Atacado")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Google Ads": _GOOGLE})
    row = next(r for r in rep["rows"] if r["leads"])
    assert (row["channel"], row["campaign"], row["investimento"]) == ("Google Ads", "PMAX | Atacado", 200.0)
    assert "Orgânico" not in rep["channel_subtotals"]


def test_atribuicao_manual_campanha_sem_gasto_na_janela_usa_nome_gravado():
    lead = {"id": "a", **_manual("meta", "cm_velha", "Campanha de julho")}
    rep = tr.build_campaign_report([lead], set(), set(), {}, "lead", "30d",
                                   spend_by_channel={"Meta Ads": _META})
    row = next(r for r in rep["rows"] if r["leads"])
    assert (row["channel"], row["campaign"], row["investimento"]) == ("Meta Ads", "Campanha de julho", 0.0)


def test_atribuicao_manual_com_canal_invalido_e_ignorada():
    lead = {"id": "a", "gclid": "g", "utm_campaign": "black", **_manual("tiktok", "x", "X")}
    assert tr.manual_attribution(lead) is None
    assert tr.lead_channel(lead) == "Google Ads"


def test_drilldown_respeita_atribuicao_manual():
    campaigns = tr._index_campaigns(_META)
    manual = {"id": "m", "utm_source": "instagram", **_manual("meta", "cm_terc", "Terceirização WA")}
    auto = {"id": "x", "ctwa_clid": "c", "meta_ad_id": "ad"}
    sel = tr.select_campaign_leads([manual, auto], "Meta Ads", "Terceirização WA", campaigns, {"x": "cm_terc"})
    assert [l["id"] for l in sel] == ["m", "x"]
    # o anúncio do lead manual aponta para outra campanha: a resposta do admin vence
    assert tr.select_campaign_leads([manual], "Meta Ads", "Atacado WA", campaigns, {"m": "cm_atac"}) == []


def test_drilldown_manual_em_campanha_sem_gasto():
    manual = {"id": "m", **_manual("meta", "cm_velha", "Campanha de julho")}
    assert [l["id"] for l in tr.select_campaign_leads(
        [manual], "Meta Ads", "Campanha de julho", tr._index_campaigns(_META), {})] == ["m"]
    assert [l["id"] for l in tr.select_campaign_leads(
        [manual], "Meta Ads", "Campanha de julho", {}, {})] == ["m"]


def test_fetch_leads_degrada_sem_colunas_do_p0():
    banco = _Banco(leads=[_g(1)])
    banco.colunas_ausentes = {"leads": ["campanha_manual_canal"]}
    out = tr._fetch_leads(banco, "lead", None, None)
    assert [l["id"] for l in out] == ["l1"]
    assert tr._P0Col.enabled is False
    assert tr._MetaAdCol.enabled is True  # o erro era só das colunas do P0


def test_fetch_leads_erro_generico_nao_desliga_p0():
    banco = _Banco(leads=[_g(1)])
    banco.ausentes = {"leads"}
    with pytest.raises(Exception):
        tr._fetch_leads(banco, "lead", None, None)
    assert tr._P0Col.enabled is True
