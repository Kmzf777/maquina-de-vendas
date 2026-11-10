"""F5 (06/11/2026): jornada do lead, atribuição pela primeira/última origem e canais com nome.

Cartões B e C de Canastra-Content-Creator/relatorios/crm-jornada-e-trafego-2026-11.md.
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.campaigns.traffic_report as tr
from app.campaigns.traffic_report import (
    aplicar_contexto_canal, atribuir_lead, build_jornadas, canal_da_entrada, derive_channel,
    jornada_do_lead, lead_channel, montar_relatorio_atribuido, motivo_sem_rastreio,
    resumo_sem_rastreio, toque_atribuido,
)

D1 = "2026-10-01T12:00:00+00:00"
D9 = "2026-10-09T12:00:00+00:00"
D12 = "2026-10-12T12:00:00+00:00"
D20 = "2026-10-20T12:00:00+00:00"


def _meta(em=D1, ad="AD1", camp_id="C_META", camp_nome="Meta | Atacado"):
    return {"occurred_at": em, "new_value": "Meta Ads", "source": "ctwa",
            "metadata": {"canal": "Meta Ads", "ctwa_clid": "CLID1", "meta_ad_id": ad,
                         "campanha_id": camp_id, "campanha_nome": camp_nome}}


def _google_lp(em=D9):
    return {"occurred_at": em, "new_value": "Google Ads", "source": "gclid",
            "metadata": {"canal": "Google Ads", "gclid": "G1", "utm_source": "google",
                         "utm_medium": "cpc", "utm_campaign": "marca"}}


def _google_botao(em=D9):
    # toque gravado por google_message_asset para quem já tinha origem (sem click id)
    return {"occurred_at": em, "new_value": "Google Ads", "source": "google_message_asset",
            "metadata": {"canal": "Google Ads", "campanha_nome": "WhatsApp do Google",
                         "texto_pronto": True, "utm_source": "google", "utm_medium": "cpc",
                         "utm_campaign": "WhatsApp do Google"}}


def _retorno(em=D9):
    return {"occurred_at": em, "new_value": "WhatsApp direto", "source": "retorno",
            "metadata": {"canal": "WhatsApp direto", "retorno": True, "dias_sem_conversa": 8}}


def _auto(em=D1, rotulo="Orgânico"):
    return {"occurred_at": em, "new_value": rotulo, "source": "inbound",
            "metadata": {"canal": rotulo, "sem_rastreio": True}}


# ── canal de um toque ──────────────────────────────────────────────────────────

def test_canal_da_entrada():
    assert canal_da_entrada(_meta()) == "Meta Ads"
    assert canal_da_entrada(_google_lp()) == "Google Ads"
    assert canal_da_entrada(_google_botao()) == "Google Ads"
    assert canal_da_entrada(_retorno()) == "WhatsApp direto"
    # a entrada automática antiga ("Orgânico") e a nova ("WhatsApp direto") são o mesmo canal
    assert canal_da_entrada(_auto()) == "WhatsApp direto"
    assert canal_da_entrada(_auto(rotulo="WhatsApp direto")) == "WhatsApp direto"
    assert canal_da_entrada({"occurred_at": D1, "metadata": {"utm_source": "instagram"}}) == "Orgânico"
    assert canal_da_entrada({"occurred_at": D1, "metadata": {}}) == "Sem rastreio"


# ── jornada (função pura) ──────────────────────────────────────────────────────

def test_jornada_meta_depois_google():
    j = jornada_do_lead({"id": "L"}, [_google_lp(), _meta()])  # fora de ordem de propósito
    assert j["primeira_origem"] == "Meta Ads" and j["ultima_origem"] == "Google Ads"
    assert j["origens"] == ["Meta Ads", "Google Ads"]
    assert j["n_toques"] == 2 and j["multicanal"] is True and j["estimado"] is False
    assert [t["canal"] for t in j["toques"]] == ["Meta Ads", "Google Ads"]


def test_jornada_google_depois_meta():
    j = jornada_do_lead({"id": "L"}, [_google_lp(D1), _meta(D9)])
    assert (j["primeira_origem"], j["ultima_origem"]) == ("Google Ads", "Meta Ads")


def test_jornada_repeticao_seguida_do_mesmo_canal_nao_repete():
    j = jornada_do_lead({"id": "L"}, [_meta(D1), _meta("2026-10-03T10:00:00+00:00"), _google_lp(D9),
                                      _meta(D12)])
    assert j["origens"] == ["Meta Ads", "Google Ads", "Meta Ads"]
    assert j["n_toques"] == 4


def test_jornada_um_canal_so_nao_e_multicanal():
    j = jornada_do_lead({"id": "L"}, [_meta(D1), _meta(D9)])
    assert j["origens"] == ["Meta Ads"] and j["multicanal"] is False


def test_jornada_lead_sem_entrada_e_estimado():
    lead = {"id": "L", "gclid": "g", "ctwa_clid": "c"}
    j = jornada_do_lead(lead, [])
    assert j["estimado"] is True and j["n_toques"] == 0
    assert j["primeira_origem"] == j["ultima_origem"] == "Google Ads"  # derive_channel de hoje
    assert jornada_do_lead({"id": "L", "origem_cadastro": "inbound"}, [])["origens"] == ["WhatsApp direto"]


def test_ultima_antes_da_venda_ignora_toque_depois_da_venda():
    entradas = [_meta(D1), _google_lp(D20)]
    j = jornada_do_lead({"id": "L"}, entradas, ate=D12)
    assert j["ultima_origem"] == "Meta Ads"
    assert toque_atribuido(entradas, "ultima", D12)["metadata"]["ctwa_clid"] == "CLID1"
    # sem corte, a última é o Google
    assert jornada_do_lead({"id": "L"}, entradas)["ultima_origem"] == "Google Ads"


def test_sem_toque_antes_do_corte_vale_o_primeiro():
    j = jornada_do_lead({"id": "L"}, [_meta(D9)], ate=D1)
    assert j["ultima_origem"] == "Meta Ads"


def test_primeira_e_ultima_recebem_o_contexto():
    lead = {"id": "L", "cliente_antigo": True}
    j = jornada_do_lead(lead, [_auto()])
    assert j["primeira_origem"] == "Cliente antigo"
    assert j["origens"] == ["WhatsApp direto"]  # a linha do tempo mostra o toque como foi


# ── caso de referência (cartão B): Meta → busca de marca no Google ─────────────

SPEND = {
    "Meta Ads": [{"campaign_id": "C_META", "campaign_name": "Meta | Atacado", "cost": 100.0}],
    "Google Ads": [{"campaign_id": "C_MARCA", "campaign_name": "Search | Marca", "cost": 50.0}],
}
SALES = {"L": {"count": 1, "value": 500.0, "frete": 0.0, "first_sold_at": D12, "last_sold_at": D12}}


def _caso(entradas, lead_extra=None):
    lead = {"id": "L", "created_at": D1, "origem_cadastro": "inbound", "ctwa_clid": "CLID1",
            "meta_ad_id": "AD1", "utm_source": "google", "utm_medium": "cpc",
            "utm_campaign": "WhatsApp do Google", **(lead_extra or {})}
    por = {a: [atribuir_lead(lead, entradas, a, D12)] for a in tr.ATRIBUICOES}
    return montar_relatorio_atribuido(por, {"L"}, {"L"}, SALES, "sale", "30d", "ultima",
                                      spend_by_channel=SPEND)


def _linhas_com_venda(rep):
    return [(r["channel"], r["campaign"]) for r in rep["rows"] if r["pedidos"]]


@pytest.mark.parametrize("toque_google", [_google_botao, _google_lp])
def test_caso_de_referencia_meta_depois_google(toque_google):
    rep = _caso([_meta(D1), toque_google(D9)])
    ultima = rep["por_atribuicao"]["ultima"]
    primeira = rep["por_atribuicao"]["primeira"]
    assert _linhas_com_venda(ultima)[0][0] == "Google Ads"
    # primeira origem: Meta Ads, campanha do dia 1 (resolvida pelo campanha_id do toque)
    assert _linhas_com_venda(primeira) == [("Meta Ads", "Meta | Atacado")]
    assert rep["rows"] == ultima["rows"] and rep["atribuicao"] == "ultima"
    assert rep["jornadas"]["leads"] == 1 and rep["jornadas"]["pedidos"] == 1
    assert rep["jornadas"]["caminhos"][0]["caminho"] == "Meta Ads → Google Ads"
    assert rep["jornadas"]["caminhos"][0]["receita"] == 500.0
    # totais iguais nos dois modos
    for k in ("leads", "clientes", "pedidos", "receita", "investimento"):
        assert ultima["total"][k] == primeira["total"][k], k


def test_caso_de_referencia_pela_busca_organica():
    rep = _caso([_meta(D1), _retorno(D9)])
    assert _linhas_com_venda(rep["por_atribuicao"]["ultima"])[0][0] == "WhatsApp direto"
    assert _linhas_com_venda(rep["por_atribuicao"]["primeira"])[0][0] == "Meta Ads"
    assert rep["jornadas"]["caminhos"][0]["caminho"] == "Meta Ads → WhatsApp direto"


def test_caso_inverso_google_depois_meta():
    rep = _caso([_google_lp(D1), _meta(D9)], {"gclid": "G1"})
    assert _linhas_com_venda(rep["por_atribuicao"]["ultima"]) == [("Meta Ads", "Meta | Atacado")]
    assert _linhas_com_venda(rep["por_atribuicao"]["primeira"])[0][0] == "Google Ads"
    # hoje (prioridade fixa) o mesmo lead cai em Google: gclid vence
    assert derive_channel({"gclid": "G1", "ctwa_clid": "CLID1"}) == "Google Ads"


def test_atribuicao_manual_vence_nos_dois_modos():
    lead = {"id": "L", "campanha_manual_canal": "google", "campanha_manual_id": "C_MARCA"}
    for a in tr.ATRIBUICOES:
        assert lead_channel(atribuir_lead(lead, [_meta(D1)], a)) == "Google Ads"


def test_totais_iguais_e_sem_rastreio_nao_cresce_com_muitos_leads():
    leads = [
        {"id": "a", "origem_cadastro": "inbound", "ctwa_clid": "x", "gclid": "g"},
        {"id": "b", "origem_cadastro": "manual"},
        {"id": "c"},
        {"id": "d", "origem_cadastro": "inbound", "tem_inbound": False, "channel": "campaign"},
    ]
    entradas = {"a": [_google_lp(D1), _meta(D9)]}
    sales = {"a": {"count": 2, "value": 10.0}, "c": {"count": 1, "value": 5.0}}
    por = {at: [atribuir_lead(l, entradas.get(l["id"], []), at) for l in leads] for at in tr.ATRIBUICOES}
    rep = montar_relatorio_atribuido(por, set(), set(), sales, "sale", "30d", "primeira")
    u, p = rep["por_atribuicao"]["ultima"]["total"], rep["por_atribuicao"]["primeira"]["total"]
    assert u == p
    hoje = tr.build_campaign_report(leads, set(), set(), sales, "sale", "30d")["total"]
    assert {k: u[k] for k in ("leads", "clientes", "pedidos", "receita")} == \
           {k: hoje[k] for k in ("leads", "clientes", "pedidos", "receita")}
    assert rep["atribuicao"] == "primeira"
    # só "c" (sem origem nenhuma) sobra em "Sem rastreio"; "d" virou disparo
    assert rep["sem_rastreio"] == {"leads": 1, "motivos": [{"motivo": "Sem origem de cadastro", "leads": 1}]}


def test_build_jornadas_top5_ordenado_por_vendas():
    leads = []
    for i, caminho in enumerate(["Meta Ads → Google Ads"] * 3 + ["Google Ads → Meta Ads"] * 2
                                + ["Meta Ads → WhatsApp direto"]):
        leads.append({"id": str(i), "_jornada": {"multicanal": True, "origens": caminho.split(" → ")}})
    leads.append({"id": "x", "_jornada": {"multicanal": False, "origens": ["Meta Ads"]}})
    sales = {"3": {"count": 1, "value": 100.0}, "4": {"count": 1, "value": 50.0}}
    j = build_jornadas(leads, sales)
    assert j["leads"] == 6 and j["clientes"] == 2 and j["total_leads"] == 7
    assert j["caminhos"][0] == {"caminho": "Google Ads → Meta Ads", "leads": 2, "clientes": 2,
                                "pedidos": 2, "receita": 150.0}
    assert [c["caminho"] for c in j["caminhos"]][1:] == ["Meta Ads → Google Ads", "Meta Ads → WhatsApp direto"]


# ── canais com nome (cartão C) ─────────────────────────────────────────────────

@pytest.mark.parametrize("origem, canal", [
    ("inbound", "WhatsApp direto"), ("manual", "Cadastro manual / disparo"),
    ("csv_import", "Importado (CSV)"), ("bling_import", "Bling"), ("reativacao_import", "Bling"),
    (None, "Sem rastreio"), ("", "Sem rastreio"), (" Inbound ", "WhatsApp direto"),
])
def test_derive_channel_por_origem_cadastro(origem, canal):
    assert derive_channel({"origem_cadastro": origem}) == canal


def test_origem_cadastro_vem_depois_dos_click_ids_e_utms():
    assert derive_channel({"origem_cadastro": "manual", "ctwa_clid": "c"}) == "Meta Ads"
    assert derive_channel({"origem_cadastro": "inbound", "utm_source": "instagram"}) == "Orgânico"
    assert derive_channel({"origem_cadastro": "csv_import", "utm_source": "google", "utm_medium": "cpc"}) == "Google Ads"


@pytest.mark.parametrize("canal, ctx, esperado", [
    ("WhatsApp direto", {"cliente_antigo": True}, "Cliente antigo"),
    ("Cadastro manual / disparo", {"cliente_antigo": True}, "Cliente antigo"),
    ("Sem rastreio", {"cliente_antigo": True}, "Cliente antigo"),
    ("WhatsApp direto", {"numero_antigo": "Canastra antigo"}, "Número antigo / outro número"),
    ("Sem rastreio", {"numero_antigo": "Evolution"}, "Número antigo / outro número"),
    ("Cadastro manual / disparo", {"numero_antigo": "X"}, "Cadastro manual / disparo"),
    ("WhatsApp direto", {"numero_antigo": "  "}, "WhatsApp direto"),
    ("WhatsApp direto", {"tem_inbound": False}, "Sem rastreio"),
    ("WhatsApp direto", {"tem_inbound": False, "lead_channel": "campaign"}, "Cadastro manual / disparo"),
    ("WhatsApp direto", {"tem_inbound": False, "lead_channel": "Bling"}, "Bling"),
    ("WhatsApp direto", {"tem_inbound": None}, "WhatsApp direto"),
    # diagnóstico de 10/11: o cadastro manual/disparo vale mesmo para quem escreveu depois
    ("WhatsApp direto", {"tem_inbound": True, "lead_channel": "manual"}, "Cadastro manual / disparo"),
    ("WhatsApp direto", {"lead_channel": "evolution"}, "WhatsApp direto"),
    ("WhatsApp direto", {"cliente_antigo": True, "lead_channel": "manual"}, "Cliente antigo"),
    ("WhatsApp direto", {"tem_inbound": True}, "WhatsApp direto"),
    ("Meta Ads", {"cliente_antigo": True, "numero_antigo": "x"}, "Meta Ads"),
    ("Google Ads", {"cliente_antigo": True}, "Google Ads"),
    ("Orgânico", {"cliente_antigo": True}, "Orgânico"),
    ("Bling", {"cliente_antigo": True}, "Bling"),
])
def test_aplicar_contexto_canal(canal, ctx, esperado):
    assert aplicar_contexto_canal(canal, **ctx) == esperado


def test_lead_channel_usa_o_contexto_do_lead():
    assert lead_channel({"origem_cadastro": "inbound", "cliente_antigo": True}) == "Cliente antigo"
    assert lead_channel({"origem_cadastro": "inbound", "numero_antigo": "Velho"}) == "Número antigo / outro número"


def test_motivo_sem_rastreio():
    assert motivo_sem_rastreio({"origem_cadastro": "inbound"}) is None  # é WhatsApp direto
    assert motivo_sem_rastreio({}) == "Sem origem de cadastro"
    assert motivo_sem_rastreio({"origem_cadastro": "inbound", "tem_inbound": False}) == "Nunca mandou mensagem"
    assert motivo_sem_rastreio({"origem_cadastro": "inbound", "tem_inbound": False,
                                "channel": "outro"}) == "Nunca mandou mensagem (cadastro 'outro')"
    r = resumo_sem_rastreio([{}, {}, {"origem_cadastro": "inbound", "tem_inbound": False}, {"gclid": "g"}])
    assert r == {"leads": 3, "motivos": [{"motivo": "Sem origem de cadastro", "leads": 2},
                                         {"motivo": "Nunca mandou mensagem", "leads": 1}]}


# ── I/O de ponta a ponta com um fake que respeita os filtros ──────────────────

class _Q:
    def __init__(self, rows):
        self._rows, self._f, self._range = list(rows), [], None

    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def order(self, *a, **k): return self

    def eq(self, col, val):
        self._f.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vs = set(vals)
        self._f.append(lambda r: r.get(col) in vs)
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(f(r) for f in self._f)]
        if self._range:
            rows = rows[self._range[0]:self._range[1] + 1]
        return type("R", (), {"data": rows})()


class _SB:
    def __init__(self, t):
        self.t = t

    def table(self, n):
        if n not in self.t:
            raise RuntimeError(f"relation {n} does not exist")
        return _Q(self.t[n])

    def rpc(self, *a, **k):
        raise RuntimeError("sem rpc")


def _tabelas():
    return {
        "leads": [
            {"id": "L", "created_at": D1, "origem_cadastro": "inbound", "ctwa_clid": "CLID1",
             "meta_ad_id": "AD1", "utm_source": "google", "utm_medium": "cpc",
             "utm_campaign": "WhatsApp do Google", "name": "Tati teste", "phone": "1"},
            {"id": "V", "created_at": D1, "origem_cadastro": "inbound", "channel": "whatsapp",
             "name": "Velho", "phone": "2"},
        ],
        "sales": [{"lead_id": "L", "value": 500.0, "sold_at": D12, "status": "ok"},
                  {"lead_id": "V", "value": 80.0, "sold_at": D12, "status": "ok"}],
        "conversations": [],
        "deals": [],
        "pipeline_stages": [],
        "ad_spend": [],
        "meta_ad_campaigns": [{"ad_id": "AD1", "campaign_id": "C_META"}],
        "lead_events": [
            {"id": "e1", "lead_id": "L", "event_type": "entrada", **_meta(D1)},
            {"id": "e2", "lead_id": "L", "event_type": "entrada", **_google_botao(D9)},
            {"id": "e3", "lead_id": "L", "event_type": "repasse", "occurred_at": D9},
        ],
        "vw_lead_contexto_canal": [
            {"lead_id": "L", "tem_inbound": True, "cliente_antigo": False, "numero_antigo": None},
            {"lead_id": "V", "tem_inbound": True, "cliente_antigo": True, "numero_antigo": None},
        ],
    }


def test_traffic_report_de_ponta_a_ponta(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(_tabelas()))
    out = tr.traffic_report(period="all", mode="sale")
    canais = {r["channel"] for r in out["rows"] if r["pedidos"]}
    assert canais == {"Google Ads", "Cliente antigo"}
    prim = {r["channel"] for r in out["por_atribuicao"]["primeira"]["rows"] if r["pedidos"]}
    assert prim == {"Meta Ads", "Cliente antigo"}
    assert out["por_atribuicao"]["ultima"]["total"] == out["por_atribuicao"]["primeira"]["total"]
    assert out["total"]["pedidos"] == 2 and out["total"]["receita"] == 580.0
    assert out["jornadas"]["caminhos"][0]["caminho"] == "Meta Ads → Google Ads"
    assert out["sem_rastreio"]["leads"] == 0
    assert "Cliente antigo" in [c["channel"] for c in out["summary"]["channels"]]


def test_traffic_report_sem_a_view_de_contexto_continua(monkeypatch):
    t = _tabelas()
    del t["vw_lead_contexto_canal"]
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(t))
    out = tr.traffic_report(period="all", mode="sale", atribuicao="primeira")
    canais = {r["channel"] for r in out["rows"] if r["pedidos"]}
    assert canais == {"Meta Ads", "WhatsApp direto"}  # sem contexto: V fica pela origem
    assert out["atribuicao"] == "primeira"


def test_campaign_leads_traz_jornada_e_motivo(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(_tabelas()))
    leads = tr.campaign_leads("Meta Ads", "(não atribuído)", period="all", mode="sale",
                              atribuicao="primeira")
    # sem gasto do Meta na janela, a linha é a do utm_campaign cru do toque (vazio)
    if not leads:
        leads = tr.campaign_leads("Meta Ads", "(sem campanha)", period="all", mode="sale",
                                  atribuicao="primeira")
    assert [l["lead_id"] for l in leads] == ["L"]
    j = leads[0]["jornada"]
    assert j["origens"] == ["Meta Ads", "Google Ads"] and j["multicanal"] is True
    assert [t["em"][:10] for t in j["toques"]] == ["2026-10-01", "2026-10-09"]
    assert leads[0]["motivo_sem_rastreio"] is None


def test_detalhe_sem_rastreio_lista_o_motivo(monkeypatch):
    t = _tabelas()
    t["leads"].append({"id": "S", "created_at": D1, "origem_cadastro": "inbound", "channel": "whatsapp"})
    t["sales"].append({"lead_id": "S", "value": 10.0, "sold_at": D12, "status": "ok"})
    t["vw_lead_contexto_canal"].append({"lead_id": "S", "tem_inbound": False, "cliente_antigo": False,
                                        "numero_antigo": None})
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(t))
    out = tr.traffic_report(period="all", mode="sale")
    assert out["sem_rastreio"] == {"leads": 1, "motivos": [{"motivo": "Nunca mandou mensagem", "leads": 1}]}
    leads = tr.campaign_leads("Sem rastreio", "(sem campanha)", period="all", mode="sale")
    assert [(l["lead_id"], l["motivo_sem_rastreio"]) for l in leads] == [("S", "Nunca mandou mensagem")]


def test_relatorio_vazio_tem_as_chaves_novas(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB({"sales": [], "leads": []}))
    out = tr.traffic_report(period="7d", mode="sale")
    assert set(out["por_atribuicao"]) == {"ultima", "primeira"}
    assert out["jornadas"]["caminhos"] == [] and out["sem_rastreio"]["leads"] == 0


def test_atribuicao_invalida_vira_ultima(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: _SB(_tabelas()))
    assert tr.traffic_report(period="all", mode="sale", atribuicao="xpto")["atribuicao"] == "ultima"


# ── toques sem click id não geram ad_conversions ───────────────────────────────
# Mesmo cenário do test_conversions_sweep (clique 06/10, venda 07/10, agora 08/10).

def _sweep():
    from app.conversions.sweep import build_candidates
    from tests.test_conversions_sweep import CLICK, ENTRADAS, NOW, VALUES, _lead
    return build_candidates, CLICK, ENTRADAS, NOW, VALUES, _lead


def _toques_sem_click(em):
    return [_google_botao(em.isoformat()), _retorno(em.isoformat()), _auto(em.isoformat())]


def test_toque_sem_click_id_nao_gera_conversao():
    build_candidates, CLICK, _, NOW, VALUES, _lead = _sweep()
    lead = _lead(ctwa_clid=None, metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(),
                                                       "motivo": "lead qualificado"}})
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(),
              "value": 180, "status": "registrada"}]
    assert build_candidates(lead=lead, entradas=_toques_sem_click(CLICK), sales=sales,
                            opportunity_at=CLICK + timedelta(hours=20), values=VALUES, now=NOW) == []


def test_toque_sem_click_id_nao_muda_a_conversao_do_clique_real():
    build_candidates, CLICK, ENTRADAS, NOW, VALUES, _lead = _sweep()
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(),
              "value": 180, "status": "registrada"}]
    kw = dict(lead=_lead(), sales=sales, opportunity_at=CLICK + timedelta(hours=20), values=VALUES, now=NOW)
    base = build_candidates(entradas=ENTRADAS, **kw)
    assert sorted(r["dedupe_key"] for r in base) == ["meta:opportunity:C1", "meta:purchase:S1"]
    com_toques = build_candidates(entradas=ENTRADAS + _toques_sem_click(CLICK + timedelta(hours=2)), **kw)
    assert com_toques == base


def test_nunca_escreveu_so_vale_para_lead_sem_entrada():
    lead = {"id": "L", "origem_cadastro": "inbound", "tem_inbound": False, "channel": "whatsapp"}
    assert lead_channel(lead) == "Sem rastreio"  # estimado: nada prova que ele escreveu
    # a entrada automática prova o inbound (a mensagem pode nem ter sido gravada ainda)
    for a in tr.ATRIBUICOES:
        v = atribuir_lead(lead, [_auto()], a)
        assert lead_channel(v) == "WhatsApp direto" and motivo_sem_rastreio(v) is None
    assert jornada_do_lead(lead, [_auto()])["primeira_origem"] == "WhatsApp direto"
