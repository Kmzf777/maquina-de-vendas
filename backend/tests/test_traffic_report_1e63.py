"""D7/D10 no /trafego (cartão 1e6381fe): receita sem frete, frete à parte e janela do modo lead."""
from datetime import date, timedelta

import app.campaigns.traffic_report as tr

ENTRADA = "2026-09-01T12:00:00-03:00"


def _dia(n: int) -> str:
    """Meio-dia de Brasília, n dias depois da entrada."""
    return (date(2026, 9, 1) + timedelta(days=n)).isoformat() + "T12:00:00-03:00"


def _venda(lid="a", value=100.0, freight=0.0, dias=1, status="registrada"):
    return {"lead_id": lid, "value": value, "freight": freight, "sold_at": _dia(dias), "status": status}


def _lead(lid="a", **kw):
    return {"id": lid, "created_at": ENTRADA, **kw}


class _Rpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class _SbB2B:
    """Só responde à rpc fn_lead_b2b."""
    def __init__(self, b2b: set[str]):
        self.b2b = b2b
        self.chamadas: list[str] = []

    def rpc(self, nome, params):
        assert nome == "fn_lead_b2b"
        self.chamadas.append(params["p_lead"])
        return _Rpc(params["p_lead"] in self.b2b)


def _sbl(monkeypatch, rows, leads=None, sb=None, mode="lead"):
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000, ordem="id": rows)
    por_id = {l["id"]: l for l in (leads or [_lead()])}
    return tr._sales_by_lead(sb, list(por_id), None, None, mode, leads_por_id=por_id)


def test_receita_sem_frete_e_frete_a_parte(monkeypatch):
    out = _sbl(monkeypatch, [_venda(value=500.0, freight=50.0)])
    assert out["a"]["value"] == 450.0
    assert out["a"]["frete"] == 50.0
    assert out["a"]["count"] == 1


def test_cancelada_fica_fora_mesmo_com_caixa_diferente(monkeypatch):
    out = _sbl(monkeypatch, [_venda(status="Cancelada"), _venda(status=" cancelado ")])
    assert "a" not in out


def test_b2c_30_dias_dentro_31_fora(monkeypatch):
    out = _sbl(monkeypatch, [_venda(value=100.0, dias=30), _venda(value=7.0, dias=31)])
    assert out["a"]["count"] == 1 and out["a"]["value"] == 100.0


def test_venda_antes_da_entrada_fica_fora(monkeypatch):
    out = _sbl(monkeypatch, [_venda(dias=-1)])
    assert "a" not in out


def test_dia_e_o_de_brasilia(monkeypatch):
    # 01/10 às 23h de Brasília = 02/10 02h UTC: ainda é o dia 30 depois da entrada (B2C dentro).
    venda = _venda(dias=0)
    venda["sold_at"] = "2026-10-02T02:00:00+00:00"
    out = _sbl(monkeypatch, [venda])
    assert out["a"]["count"] == 1


def test_b2b_pelo_segmento_89_dias_dentro_91_fora(monkeypatch):
    sb = _SbB2B(set())
    out = _sbl(monkeypatch, [_venda(value=100.0, dias=89), _venda(value=5.0, dias=91)],
               leads=[_lead(segmento="atacado")], sb=sb)
    assert out["a"]["count"] == 1 and out["a"]["value"] == 100.0
    assert sb.chamadas == []  # segmento já basta, sem ida ao banco


def test_b2b_pela_rpc_fn_lead_b2b(monkeypatch):
    sb = _SbB2B({"a"})
    out = _sbl(monkeypatch, [_venda(dias=89)], leads=[_lead(segmento="consumo")], sb=sb)
    assert out["a"]["count"] == 1
    assert sb.chamadas == ["a"]


def test_b2b_so_e_consultado_para_venda_entre_31_e_90_dias(monkeypatch):
    sb = _SbB2B(set())
    out = _sbl(monkeypatch, [_venda(dias=5), _venda(dias=200)], sb=sb)
    assert out["a"]["count"] == 1
    assert sb.chamadas == []


def test_rpc_com_erro_vira_b2c(monkeypatch):
    out = _sbl(monkeypatch, [_venda(dias=60)], sb=None)
    assert "a" not in out


def test_modo_venda_nao_aplica_a_janela(monkeypatch):
    out = _sbl(monkeypatch, [_venda(dias=200, value=80.0, freight=10.0)], mode="sale")
    assert out["a"]["value"] == 70.0 and out["a"]["frete"] == 10.0


def test_roas_e_receita_sem_frete_sobre_investimento():
    spend = {"Google Ads": [{"campaign_id": "c1", "campaign_name": "black", "cost": 100.0}]}
    leads = [{"id": "a", "gclid": "1", "utm_campaign": "black", "utm_medium": "cpc"}]
    out = tr.build_campaign_report(leads, set(), set(),
                                   {"a": {"count": 1, "value": 450.0, "frete": 50.0}},
                                   "lead", "30d", spend_by_channel=spend)
    row = next(r for r in out["rows"] if r["campaign"] == "black")
    assert row["receita"] == 450.0 and row["frete"] == 50.0
    assert row["roas"] == 4.5 and row["ticket_medio"] == 450.0
    assert out["total"]["frete"] == 50.0 and out["total"]["roas"] == 4.5
    sub = out["channel_subtotals"]["Google Ads"]
    assert sub["frete"] == 50.0 and sub["roas"] == 4.5


def test_resumo_tem_frete():
    spend = {"Google Ads": [{"campaign_id": "c1", "campaign_name": "black", "cost": 100.0}]}
    leads = [{"id": "a", "gclid": "1", "utm_campaign": "black", "utm_medium": "cpc"},
             {"id": "b", "utm_source": "", "utm_campaign": ""}]
    sales = {"a": {"count": 1, "value": 450.0, "frete": 50.0},
             "b": {"count": 1, "value": 90.0, "frete": 10.0}}
    report = tr.build_campaign_report(leads, set(), set(), sales, "lead", "30d", spend_by_channel=spend)
    summary = tr.build_report_summary(report, leads, sales)
    assert summary["cost"]["receita"] == 450.0 and summary["cost"]["frete"] == 50.0
    assert summary["cost"]["roas"] == 4.5
    google = next(c for c in summary["channels"] if c["channel"] == "Google Ads")
    assert google["frete"] == 50.0 and google["roas"] == 4.5


def test_relatorio_e_resumo_vazios_tem_frete_zero():
    vazio = tr._empty_report("lead", "30d")
    assert vazio["total"]["frete"] == 0.0
    assert vazio["summary"]["cost"]["frete"] == 0.0
    assert tr._empty_summary("Google Ads", "x")["frete"] == 0.0


def test_traffic_report_modo_lead_aplica_janela_e_frete(monkeypatch):
    leads = [_lead("a", gclid="1", utm_campaign="black")]
    vendas = [_venda(value=500.0, freight=50.0, dias=10), _venda(value=300.0, dias=40)]
    monkeypatch.setattr(tr, "get_supabase", lambda: None)
    monkeypatch.setattr(tr, "_fetch_leads", lambda sb, mode, lo, hi: leads)
    monkeypatch.setattr(tr, "_conversed_ids", lambda sb, ids: set())
    monkeypatch.setattr(tr, "_closer_ids", lambda sb, ids: set())
    monkeypatch.setattr(tr, "_spend_by_channel", lambda sb, lo, hi: {})
    monkeypatch.setattr(tr, "_meta_campaign_by_lead", lambda sb, ls: {})
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000, ordem="id": vendas)
    out = tr.traffic_report("30d", "lead")
    assert out["total"]["receita"] == 450.0
    assert out["total"]["frete"] == 50.0
    assert out["total"]["pedidos"] == 1


def test_serie_diaria_receita_sem_frete():
    dia = date(2026, 9, 2)
    serie = tr.build_campaign_timeseries([dia], [], [
        {"value": 500.0, "freight": 50.0, "sold_at": "2026-09-02T12:00:00-03:00"}])
    assert serie[0]["receita"] == 450.0 and serie[0]["vendas"] == 1
