# backend/tests/test_conversions_sweep.py
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.conversions import sweep as sweep_mod
from app.conversions.sweep import build_candidates, opportunity_from

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
CLICK = NOW - timedelta(days=2)
BR = timezone(timedelta(hours=-3))


def _lead(**kw):
    base = {"id": "L1", "stage": "atacado", "ja_era_cliente": None, "metadata": {},
            "created_at": CLICK.isoformat(), "ctwa_clid": "C1", "gclid": None, "gbraid": None, "wbraid": None}
    base.update(kw)
    return base


ENTRADAS = [{"occurred_at": CLICK.isoformat(), "metadata": {"ctwa_clid": "C1", "campanha_nome": "Atacado | WA"}}]
VALUES = {("atacado", "lead"): 5.0, ("atacado", "qualified"): 80.0, ("atacado", "opportunity"): 300.0}


def _keys(rows):
    return sorted(r["dedupe_key"] for r in rows)


def _by_key(rows):
    return {r["dedupe_key"]: r for r in rows}


# ── build_candidates (puro) ──────────────────────────────────────────────────

def test_lead_com_clique_gera_evento_lead_com_valor():
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]
    r = rows[0]
    assert r["platform"] == "meta" and r["stage"] == "lead" and r["value"] == 5.0
    assert r["segment"] == "atacado" and r["campaign_name"] == "Atacado | WA"
    assert r["event_at"] == CLICK.isoformat() and r["click_id_type"] == "ctwa_clid"
    assert r["click_at"] == CLICK.isoformat() and r["lead_id"] == "L1" and r["sale_id"] is None
    assert r["status"] == "pendente" and r["currency"] == "BRL"


def test_repasse_valido_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1", "meta:qualified:C1"]
    q = _by_key(rows)["meta:qualified:C1"]
    assert q["value"] == 80.0 and q["event_at"] == (CLICK + timedelta(hours=3)).isoformat()


def test_repasse_de_fallback_nao_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": CLICK.isoformat(), "motivo": "IA temporariamente indisponível — x"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_repasse_antes_do_clique_nao_tem_clique_atribuido():
    lead = _lead(metadata={"handoff": {"at": (CLICK - timedelta(hours=1)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_oportunidade_e_venda():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 180, "status": "registrada"},
             {"id": "S2", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 99, "status": "cancelada"}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales,
                            opportunity_at=CLICK + timedelta(hours=20), values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1", "meta:opportunity:C1", "meta:purchase:S1"]
    p = _by_key(rows)["meta:purchase:S1"]
    assert p["value"] == 180.0 and p["sale_id"] == "S1" and p["event_id"] == "purchase:S1"
    assert _by_key(rows)["meta:opportunity:C1"]["value"] == 300.0


def test_venda_cancelada_com_caixa_diferente_tambem_sai():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 99, "status": "Cancelada"}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales, opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_venda_fora_da_janela_meta_nao_entra_mas_google_entra():
    entradas = ENTRADAS + [{"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1"}}]
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=10)).isoformat(), "value": 500, "status": None}]
    rows = build_candidates(lead=_lead(), entradas=entradas, sales=sales, opportunity_at=None, values=VALUES,
                            now=CLICK + timedelta(days=11))
    assert "google:purchase:S1" in _keys(rows)
    assert "meta:purchase:S1" not in _keys(rows)


def test_ja_era_cliente_so_venda():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 180, "status": None}]
    lead = _lead(ja_era_cliente=True, metadata={"handoff": {"at": CLICK.isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=sales,
                            opportunity_at=CLICK + timedelta(hours=5), values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:purchase:S1"]


def test_segmento_geral_sem_valor_configurado_vai_none():
    rows = build_candidates(lead=_lead(stage="pending"), entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows[0]["segment"] == "geral" and rows[0]["value"] is None


def test_evento_mais_velho_que_a_janela_de_envio_nao_entra():
    # Meta: event_time > 7 dias antes de agora é recusado — não adianta enfileirar.
    old = NOW - timedelta(days=8)
    entradas = [{"occurred_at": old.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    rows = build_candidates(lead=_lead(created_at=old.isoformat()), entradas=entradas, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_google_clique_com_mais_de_90_dias_nao_entra_mesmo_com_venda_recente():
    # O Google importa clique de até 90 dias (a mesma regra que o sender aplica): venda de 20 dias
    # atrás atribuída a um clique de 100 dias seria marcada fora_da_janela na hora do envio.
    velho = NOW - timedelta(days=100)
    entradas = [{"occurred_at": velho.isoformat(), "metadata": {"gclid": "G1"}}]
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (NOW - timedelta(days=20)).isoformat(), "value": 500, "status": None}]
    rows = build_candidates(lead=_lead(ctwa_clid=None, created_at=velho.isoformat()), entradas=entradas, sales=sales,
                            opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_lead_sem_entrada_usa_fallback():
    rows = build_candidates(lead=_lead(), entradas=[], sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_um_evento_lead_por_clique_e_so_na_plataforma_do_clique():
    c2 = CLICK + timedelta(days=1)
    entradas = ENTRADAS + [
        {"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1", "campanha_nome": "Search"}},
        {"occurred_at": c2.isoformat(), "metadata": {"ctwa_clid": "C2"}},
    ]
    rows = build_candidates(lead=_lead(ctwa_clid="C2"), entradas=entradas, sales=[], opportunity_at=None,
                            values=VALUES, now=NOW)
    assert _keys(rows) == ["google:lead:G1", "meta:lead:C1", "meta:lead:C2"]
    r = _by_key(rows)
    assert r["meta:lead:C2"]["event_at"] == c2.isoformat()
    assert r["google:lead:G1"]["click_id_type"] == "gclid" and r["google:lead:G1"]["campaign_name"] == "Search"


def test_dois_cliques_da_mesma_plataforma_no_mesmo_instante_geram_dois_leads():
    entradas = [{"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1", "gbraid": "B1"}}]
    rows = build_candidates(lead=_lead(ctwa_clid=None), entradas=entradas, sales=[], opportunity_at=None,
                            values=VALUES, now=NOW)
    assert _keys(rows) == ["google:lead:B1", "google:lead:G1"]


def test_mesmo_clique_repetido_vira_uma_linha_com_a_hora_mais_antiga():
    depois = CLICK + timedelta(hours=5)
    entradas = [{"occurred_at": depois.isoformat(), "metadata": {"ctwa_clid": "C1"}},
                {"occurred_at": CLICK.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    rows = build_candidates(lead=_lead(), entradas=entradas, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]
    assert rows[0]["event_at"] == CLICK.isoformat()


def test_etapas_usam_o_clique_mais_recente_antes_do_evento():
    c2 = CLICK + timedelta(days=1)
    c3 = CLICK + timedelta(days=1, hours=10)  # depois do repasse: não pode levar o crédito
    entradas = ENTRADAS + [{"occurred_at": c2.isoformat(), "metadata": {"ctwa_clid": "C2"}},
                           {"occurred_at": c3.isoformat(), "metadata": {"ctwa_clid": "C3"}}]
    lead = _lead(ctwa_clid="C3", metadata={"handoff": {"at": (c2 + timedelta(hours=1)).isoformat(), "motivo": "ok"}})
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (c3 + timedelta(hours=1)).isoformat(), "value": 10, "status": None}]
    rows = build_candidates(lead=lead, entradas=entradas, sales=sales, opportunity_at=None, values=VALUES, now=NOW)
    r = _by_key(rows)
    assert "meta:qualified:C2" in r and "meta:qualified:C3" not in r
    assert r["meta:purchase:S1"]["click_id"] == "C3"


def test_evento_no_futuro_ainda_nao_entra():
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=[], opportunity_at=NOW + timedelta(days=1),
                            values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1"]


def test_horario_sem_fuso_nao_derruba_a_varredura():
    # handoff.at sem fuso (gravação antiga/manual) é lido como UTC em vez de estourar
    # TypeError na comparação com datetimes com fuso.
    naive = (CLICK + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    lead = _lead(metadata={"handoff": {"at": naive, "motivo": "ok"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:lead:C1", "meta:qualified:C1"]
    assert _by_key(rows)["meta:qualified:C1"]["event_at"] == (CLICK + timedelta(hours=1)).isoformat()


# ── opportunity_from ────────────────────────────────────────────────────────

def test_oportunidade_pega_a_primeira_entre_orcamento_e_proposta_enviada():
    criado = datetime(2026, 10, 7, 15, tzinfo=timezone.utc)
    quotes = [{"lead_id": "L1", "status": "enviado", "quoted_at": "2026-10-07", "created_at": criado.isoformat()}]
    propostas = [{"lead_id": "L1", "occurred_at": (criado - timedelta(hours=2)).isoformat()}]
    assert opportunity_from(quotes, propostas) == criado - timedelta(hours=2)
    assert opportunity_from(quotes, []) == criado
    assert opportunity_from([], []) is None


def test_quoted_at_e_data_sem_hora():
    # quoted_at é DATE: no mesmo dia vale a hora exata de created_at; datado para depois,
    # vale a meia-noite (horário de Brasília) do dia do orçamento — nunca antes de existir.
    criado = datetime(2026, 10, 3, 15, tzinfo=timezone.utc)
    q = {"lead_id": "L1", "status": "enviado", "created_at": criado.isoformat()}
    assert opportunity_from([{**q, "quoted_at": "2026-10-03"}], []) == criado
    assert opportunity_from([{**q, "quoted_at": "2026-10-01"}], []) == criado
    assert opportunity_from([{**q, "quoted_at": "2026-10-05"}], []) == datetime(2026, 10, 5, tzinfo=BR)
    assert opportunity_from([{**q, "quoted_at": date(2026, 10, 5)}], []) == datetime(2026, 10, 5, tzinfo=BR)


# ── I/O com supabase falso ──────────────────────────────────────────────────

class _Q:
    """Query builder fake: devolve as linhas da tabela aplicando só `eq`/`in_` em colunas que a
    linha tem (o resto — gte, or_, order, range, JSON path — é ignorado) e registra as chamadas."""
    def __init__(self, name, data, log):
        self._name, self._data, self._log = name, list(data), log

    def __getattr__(self, attr):
        def _call(*a, **k):
            self._log.append((self._name, attr, a, k))
            if attr in ("eq", "in_"):
                col, val = a
                ok = (lambda v: v == val) if attr == "eq" else (lambda v: v in set(val))
                self._data = [r for r in self._data if col not in r or ok(r[col])]
            return self
        return _call

    def execute(self):
        return MagicMock(data=self._data)


def _fake_sb(tables, upserts, log):
    sb = MagicMock()

    def _table(name):
        if name == "ad_conversions":
            q = MagicMock()
            q.upsert.side_effect = lambda rows, **kw: upserts.append((rows, kw)) or MagicMock()
            return q
        return _Q(name, tables.get(name, []), log)
    sb.table.side_effect = _table
    return sb


def test_run_sweep_faz_upsert_com_ignore_duplicates(monkeypatch):
    tables = {
        "ad_conversion_values": [{"segment": "atacado", "stage": "lead", "value": 5}],
        "lead_events": [{"lead_id": "L1", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C1"}}],
        "leads": [_lead()],
        "sales": [], "quotes": [],
    }
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb(tables, upserts, log))
    n = sweep_mod.run_sweep(now=NOW)
    assert n >= 1
    rows, kw = upserts[0]
    assert kw == {"on_conflict": "dedupe_key", "ignore_duplicates": True}
    assert any(r["dedupe_key"] == "meta:lead:C1" and r["value"] == 5.0 for r in rows)
    # todas as linhas de um upsert em lote precisam das MESMAS chaves (PostgREST usa ?columns=)
    assert len({tuple(sorted(r)) for r in rows}) == 1


def test_run_sweep_quebra_os_ids_em_blocos_de_200(monkeypatch):
    ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(450)]
    tables = {"lead_events": [{"lead_id": i, "event_type": "entrada", "occurred_at": CLICK.isoformat(), "metadata": {}}
                              for i in ids],
              "leads": [], "sales": [], "quotes": [], "ad_conversion_values": []}
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb(tables, upserts, log))
    sweep_mod.run_sweep(now=NOW)
    ins = [(t, len(list(a[1]))) for (t, attr, a, _k) in log if attr == "in_" and a[0] in ("id", "lead_id")]
    assert ins and max(n for _t, n in ins) <= 200
    assert sorted(n for t, n in ins if t == "leads") == [50, 200, 200]


def test_paged_segue_ate_a_pagina_incompleta():
    paginas = [[{"i": n} for n in range(1000)], [{"i": n} for n in range(1000)], [{"i": 1}]]
    ranges = []

    class _P:
        def range(self, a, b):
            ranges.append((a, b))
            return self

        def execute(self):
            return MagicMock(data=paginas[len(ranges) - 1])

    rows = sweep_mod._paged(lambda: _P())
    assert len(rows) == 2001
    assert ranges == [(0, 999), (1000, 1999), (2000, 2999)]


def test_um_lead_quebrado_nao_derruba_a_varredura(monkeypatch):
    tables = {
        "ad_conversion_values": [],
        "lead_events": [{"lead_id": "L1", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C1"}},
                        {"lead_id": "L2", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C9"}}],
        "leads": [_lead(id="L2", ctwa_clid="C9"), _lead()],
        "sales": [], "quotes": [],
    }
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb(tables, upserts, log))
    real = sweep_mod.build_candidates

    def _flaky(*, lead, **kw):
        if lead["id"] == "L2":
            raise ValueError("dado podre")
        return real(lead=lead, **kw)
    monkeypatch.setattr(sweep_mod, "build_candidates", _flaky)
    sweep_mod.run_sweep(now=NOW)
    keys = [r["dedupe_key"] for rows, _ in upserts for r in rows]
    assert keys == ["meta:lead:C1"]
