"""Visão do período (/trafego, 12/11/2026): cada coluna conta pela própria data.

Topo (leads, conversas, closer) = o modo "lead" no mesmo período; vendas (clientes, pedidos,
receita, frete) = o modo "sale" no mesmo período. O banco falso daqui FILTRA de verdade
(gte/lte/in_/eq), senão os três modos devolveriam as mesmas linhas e o teste não provaria nada.
"""
from datetime import datetime, timezone

import app.campaigns.traffic_report as tr


def _cmp_val(v):
    if isinstance(v, str) and len(v) > 10 and v[4] == "-":
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return v


class _Q:
    def __init__(self, rows):
        self._rows = list(rows)
        self._f = []
        self._range = None

    def select(self, *a, **k): return self
    def order(self, *a, **k): return self

    def gte(self, col, v):
        self._f.append(lambda r: r.get(col) is not None and _cmp_val(r[col]) >= _cmp_val(v)); return self

    def lte(self, col, v):
        self._f.append(lambda r: r.get(col) is not None and _cmp_val(r[col]) <= _cmp_val(v)); return self

    def in_(self, col, vs):
        s = set(vs); self._f.append(lambda r: r.get(col) in s); return self

    def eq(self, col, v):
        self._f.append(lambda r: r.get(col) == v); return self

    def range(self, a, b):
        self._range = (a, b); return self

    def execute(self):
        rows = [r for r in self._rows if all(f(r) for f in self._f)]
        if self._range:
            rows = rows[self._range[0]:self._range[1] + 1]
        return type("R", (), {"data": rows})()


class _SB:
    def __init__(self, t): self.t = t
    def table(self, n): return _Q(self.t.get(n, []))
    def rpc(self, *a, **k): return _Q([])


def _lead(id, created, **kw):
    base = {"id": id, "name": id, "phone": "", "created_at": created, "gclid": "", "gbraid": "",
            "wbraid": "", "fbclid": "", "ctwa_clid": "", "utm_source": "", "utm_medium": "",
            "utm_campaign": "", "traffic_type": "", "origem_cadastro": "", "segmento": None,
            "stage": None, "meta_ad_id": ""}
    base.update(kw)
    return base


TABLES = {
    "leads": [
        # Meta, entrou no período, foi ao closer, não comprou
        _lead("A", "2026-11-06T15:00:00Z", meta_ad_id="ad1"),
        _lead("A2", "2026-11-07T15:00:00Z", meta_ad_id="ad1"),
        # Google, entrou e comprou no período; comprou de novo DEPOIS do período
        _lead("B", "2026-11-07T15:00:00Z", gclid="g1", utm_campaign="black", utm_medium="cpc"),
        # Google antigo que comprou no período
        _lead("C", "2026-10-01T15:00:00Z", gclid="g2", utm_campaign="black", utm_medium="cpc"),
        # importado do Bling, comprou no período
        _lead("D", "2026-11-06T15:00:00Z", origem_cadastro="bling_import"),
        # sem rastreio antigo, comprou no período (venda grande)
        _lead("E", "2026-09-01T15:00:00Z"),
    ],
    "conversations": [
        {"id": "c1", "lead_id": "A", "last_customer_message_at": "2026-11-06T16:00:00Z"},
        {"id": "c2", "lead_id": "A2", "last_customer_message_at": "2026-11-07T16:00:00Z"},
        {"id": "c3", "lead_id": "B", "last_customer_message_at": "2026-11-07T16:00:00Z"},
    ],
    "lead_events": [{"id": "e1", "lead_id": "A", "event_type": "repasse"}],
    "sales": [
        {"id": "s1", "lead_id": "B", "value": 100.0, "freight": 0, "sold_at": "2026-11-08T15:00:00Z", "status": "pago"},
        {"id": "s2", "lead_id": "B", "value": 70.0, "freight": 0, "sold_at": "2026-11-20T15:00:00Z", "status": "pago"},
        {"id": "s3", "lead_id": "C", "value": 200.0, "freight": 0, "sold_at": "2026-11-09T15:00:00Z", "status": "pago"},
        {"id": "s4", "lead_id": "D", "value": 50.0, "freight": 0, "sold_at": "2026-11-10T15:00:00Z", "status": "pago"},
        {"id": "s5", "lead_id": "E", "value": 300.0, "freight": 0, "sold_at": "2026-11-10T15:00:00Z", "status": "pago"},
        {"id": "s6", "lead_id": "E", "value": 999.0, "freight": 0, "sold_at": "2026-11-10T16:00:00Z", "status": "cancelado"},
    ],
    "ad_spend": [
        {"id": 1, "platform": "google", "campaign_id": "111", "campaign_name": "Black", "cost": 100.0, "date": "2026-11-06"},
        {"id": 2, "platform": "meta", "campaign_id": "222", "campaign_name": "Atacado | WA", "cost": 50.0, "date": "2026-11-07"},
        {"id": 3, "platform": "meta", "campaign_id": "222", "campaign_name": "Atacado | WA", "cost": 999.0, "date": "2026-10-01"},
    ],
    "meta_ad_campaigns": [{"ad_id": "ad1", "campaign_id": "222"}],
}


def _rodar(monkeypatch, mode):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(TABLES))
    return tr.traffic_report(mode=mode, date_from="2026-11-05", date_to="2026-11-11")


def _por_linha(rep):
    return {(r["channel"], r["campaign"]): r for r in rep["rows"]}


def test_totais_do_periodo_batem_com_lead_no_topo_e_com_venda_nas_vendas(monkeypatch):
    lead = _rodar(monkeypatch, "lead")
    sale = _rodar(monkeypatch, "sale")
    per = _rodar(monkeypatch, "periodo")
    assert per["mode"] == "periodo"
    for k in ("leads", "conversas", "closer"):
        assert per["total"][k] == lead["total"][k], k
    for k in ("clientes", "pedidos", "receita", "frete"):
        assert per["total"][k] == sale["total"][k], k
    assert per["total"]["investimento"] == lead["total"]["investimento"] == 150.0
    # o caso do print: o "lead" esconde vendas e o "sale" esconde leads; o período mostra os dois
    assert lead["total"]["pedidos"] != per["total"]["pedidos"]
    assert sale["total"]["leads"] != per["total"]["leads"]


def test_linhas_do_periodo(monkeypatch):
    per = _por_linha(_rodar(monkeypatch, "periodo"))
    google = per[("Google Ads", "Black")]
    # B entrou; C é antigo mas comprou no período. A venda de B de 20/11 fica de fora.
    assert (google["leads"], google["pedidos"], google["receita"]) == (1, 2, 300.0)
    assert google["investimento"] == 100.0 and google["roas"] == 3.0
    assert google["conversao"] == 2.0  # pedidos ÷ leads do período: taxa do período, não coorte
    meta = per[("Meta Ads", "Atacado | WA")]
    assert (meta["leads"], meta["closer"], meta["pedidos"], meta["investimento"]) == (2, 1, 0, 50.0)
    assert meta["conversao"] == 0.0
    bling = per[("Bling", "(sem campanha)")]
    assert (bling["leads"], bling["pedidos"], bling["receita"]) == (0, 1, 50.0)
    assert bling["conversao"] is None  # sem lead no período: "—", nunca 0% nem infinito
    sem = per[("Sem rastreio", "(sem campanha)")]
    assert (sem["leads"], sem["pedidos"], sem["receita"]) == (0, 1, 300.0)  # cancelada fora


def test_subtotais_e_resumo_do_periodo(monkeypatch):
    per = _rodar(monkeypatch, "periodo")
    sub = per["channel_subtotals"]["Google Ads"]
    assert (sub["leads"], sub["pedidos"], sub["receita"], sub["investimento"]) == (1, 2, 300.0, 100.0)
    f = per["summary"]["funnel"]
    assert (f["leads"], f["closer"], f["pedidos"], f["receita"]) == (3, 2, 4, 650.0)
    assert per["total"]["conversao"] == round(4 / 3, 4)
    assert per["total"]["roas"] == 2.0  # receita paga 300 ÷ investimento 150


def test_merge_puro_casa_por_canal_e_campanha():
    lead = {"rows": [{**tr._new_row("Meta Ads", "X"), "leads": 10, "conversas": 8, "closer": 3,
                      "clientes": 1, "pedidos": 1, "receita": 10.0, "investimento": 40.0}]}
    sale = {"rows": [{**tr._new_row("Meta Ads", "X"), "leads": 2, "conversas": 2, "closer": 2,
                      "clientes": 2, "pedidos": 3, "receita": 90.0, "investimento": 40.0},
                     {**tr._new_row("Bling", "(sem campanha)"), "leads": 5, "clientes": 5,
                      "pedidos": 5, "receita": 500.0}]}
    out = tr.merge_period_report(lead, sale, "custom")
    x = _por_linha(out)[("Meta Ads", "X")]
    assert (x["leads"], x["closer"], x["clientes"], x["pedidos"], x["receita"]) == (10, 3, 2, 3, 90.0)
    assert x["investimento"] == 40.0 and x["roas"] == 2.25 and x["conversao"] == 0.3
    assert _por_linha(out)[("Bling", "(sem campanha)")]["leads"] == 0


def test_campaign_leads_periodo_junta_quem_entrou_e_quem_comprou(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(TABLES))
    leads = tr.campaign_leads("Google Ads", "Black", mode="periodo",
                              date_from="2026-11-05", date_to="2026-11-11")
    por_id = {l["lead_id"]: l for l in leads}
    assert set(por_id) == {"B", "C"}
    assert por_id["B"]["entrou_no_periodo"] is True and por_id["C"]["entrou_no_periodo"] is False
    assert por_id["B"]["valor"] == 100.0  # só a venda do período
    assert por_id["C"]["comprou"] is True


def test_campaign_detail_periodo(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(TABLES))
    d = tr.campaign_detail("Google Ads", "Black", mode="periodo",
                           date_from="2026-11-05", date_to="2026-11-11")
    s = d["summary"]
    assert (s["leads"], s["pedidos"], s["receita"], s["investimento"]) == (1, 2, 300.0, 100.0)
    serie = {p["date"]: p for p in d["timeseries"]}
    assert serie["2026-11-07"]["leads"] == 1
    assert serie["2026-11-09"]["vendas"] == 1 and serie["2026-11-08"]["vendas"] == 1
    m = tr.campaign_detail("Meta Ads", "Atacado | WA", mode="periodo",
                           date_from="2026-11-05", date_to="2026-11-11")["summary"]
    assert (m["leads"], m["closer"], m["pedidos"], m["investimento"]) == (2, 1, 0, 50.0)
