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

GENTRADAS = [{"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1", "campanha_nome": "Search"}}]


def test_clique_google_sozinho_nao_gera_evento():
    # Spec 13/10: o clique (lead) já é contado no Google pelas conversões do site e por "Leads de
    # mensagens"; mandar de novo contaria a mesma pessoa duas vezes. Só qualificado/oportunidade/venda.
    rows = build_candidates(lead=_lead(ctwa_clid=None), entradas=GENTRADAS, sales=[], opportunity_at=None,
                            values=VALUES, now=NOW)
    assert rows == []


def test_clique_google_com_repasse_gera_so_qualified():
    lead = _lead(ctwa_clid=None,
                 metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=GENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["google:qualified:G1"]
    r = rows[0]
    assert r["segment"] == "atacado" and r["campaign_name"] == "Search"
    assert r["click_id_type"] == "gclid" and r["click_at"] == CLICK.isoformat()
    assert r["lead_id"] == "L1" and r["sale_id"] is None
    assert r["status"] == "pendente" and r["currency"] == "BRL"


def test_clique_meta_nao_gera_evento_lead():
    # A Meta já conta a conversa; só o repasse (qualified) vira LeadSubmitted.
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_repasse_valido_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": (CLICK + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:qualified:C1"]
    q = _by_key(rows)["meta:qualified:C1"]
    assert q["value"] == 80.0 and q["event_at"] == (CLICK + timedelta(hours=3)).isoformat()


def test_repasse_de_fallback_nao_gera_qualified():
    lead = _lead(metadata={"handoff": {"at": CLICK.isoformat(), "motivo": "IA temporariamente indisponível — x"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_repasse_antes_do_clique_nao_tem_clique_atribuido():
    lead = _lead(metadata={"handoff": {"at": (CLICK - timedelta(hours=1)).isoformat(), "motivo": "lead qualificado"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


def test_oportunidade_e_venda():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 180, "status": "registrada"},
             {"id": "S2", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 99, "status": "cancelada"}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales,
                            opportunity_at=CLICK + timedelta(hours=20), values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:opportunity:C1", "meta:purchase:S1"]
    p = _by_key(rows)["meta:purchase:S1"]
    assert p["value"] == 180.0 and p["sale_id"] == "S1" and p["event_id"] == "purchase:S1"
    assert _by_key(rows)["meta:opportunity:C1"]["value"] == 300.0


def test_venda_do_mesmo_dia_usa_a_hora_do_lancamento():
    """`sold_at` é só a data (gravada 12:00/15:00 UTC). Clique às 14:00 BRT e venda lançada às
    15:00 BRT do mesmo dia: com o sold_at cru (09:00 BRT) a venda pareceria ANTES do clique e
    nunca teria clique atribuído. No mesmo dia vale a hora de `created_at`."""
    click = datetime(2026, 10, 7, 14, tzinfo=BR)
    entradas = [{"occurred_at": click.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    criado = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": "2026-10-07T12:00:00+00:00",
              "created_at": criado.isoformat(), "value": 180, "status": None}]
    rows = build_candidates(lead=_lead(created_at=click.isoformat()), entradas=entradas, sales=sales,
                            opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:purchase:S1"]
    assert rows[0]["event_at"] == criado.isoformat()


def test_venda_retroativa_mantem_o_sold_at():
    # Lançada dias depois (created_at em outro dia): a data do documento é a que vale.
    entradas = [{"occurred_at": datetime(2026, 10, 2, 14, tzinfo=BR).isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": "2026-10-03T12:00:00+00:00",
              "created_at": "2026-10-07T18:00:00+00:00", "value": 180, "status": None}]
    rows = build_candidates(lead=_lead(created_at="2026-10-02T17:00:00+00:00"), entradas=entradas, sales=sales,
                            opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:purchase:S1"]
    assert rows[0]["event_at"] == datetime(2026, 10, 3, 12, tzinfo=timezone.utc).isoformat()


def test_venda_sem_created_at_usa_o_sold_at():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 1, "status": None}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales, opportunity_at=None, values=VALUES, now=NOW)
    assert rows[0]["event_at"] == (CLICK + timedelta(days=1)).isoformat()


_HANDOFF = {"handoff": {"at": (CLICK + timedelta(hours=6)).isoformat(), "motivo": "lead qualificado"}}


def test_campanha_cai_no_utm_campaign_da_entrada():
    for meta in ({"gclid": "G1", "utm_campaign": "search-atacado"},
                 {"gclid": "G1", "campanha_nome": "", "utm_campaign": "search-atacado"}):
        rows = build_candidates(lead=_lead(ctwa_clid=None, metadata=_HANDOFF),
                                entradas=[{"occurred_at": CLICK.isoformat(), "metadata": meta}],
                                sales=[], opportunity_at=None, values=VALUES, now=NOW)
        assert rows[0]["campaign_name"] == "search-atacado"
    rows = build_candidates(lead=_lead(ctwa_clid=None, metadata=_HANDOFF), entradas=[{"occurred_at": CLICK.isoformat(), "metadata": {
        "gclid": "G1", "campanha_nome": "Search | Atacado", "utm_campaign": "search-atacado"}}],
        sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert rows[0]["campaign_name"] == "Search | Atacado"


def test_venda_cancelada_com_caixa_diferente_tambem_sai():
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 99, "status": "Cancelada"}]
    rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales, opportunity_at=None, values=VALUES, now=NOW)
    assert rows == []


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
    rows = build_candidates(lead=_lead(stage="pending", ctwa_clid=None, metadata=_HANDOFF), entradas=GENTRADAS,
                            sales=[], opportunity_at=None, values=VALUES, now=NOW)
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
    assert rows == []


def test_cliques_sem_etapa_nao_geram_evento_em_nenhuma_plataforma():
    c2 = CLICK + timedelta(days=1)
    entradas = ENTRADAS + [
        {"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1", "campanha_nome": "Search"}},
        {"occurred_at": c2.isoformat(), "metadata": {"ctwa_clid": "C2"}},
    ]
    rows = build_candidates(lead=_lead(ctwa_clid="C2"), entradas=entradas, sales=[], opportunity_at=None,
                            values=VALUES, now=NOW)
    assert rows == []


def test_dois_cliques_da_mesma_plataforma_no_mesmo_instante_geram_um_qualified():
    entradas = [{"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1", "gbraid": "B1"}}]
    rows = build_candidates(lead=_lead(ctwa_clid=None, metadata=_HANDOFF), entradas=entradas, sales=[],
                            opportunity_at=None, values=VALUES, now=NOW)
    assert len(rows) == 1 and rows[0]["platform"] == "google" and rows[0]["stage"] == "qualified"


def test_mesmo_clique_repetido_vira_uma_linha():
    depois = CLICK + timedelta(hours=5)
    entradas = [{"occurred_at": depois.isoformat(), "metadata": {"gclid": "G1"}},
                {"occurred_at": CLICK.isoformat(), "metadata": {"gclid": "G1"}}]
    rows = build_candidates(lead=_lead(ctwa_clid=None, metadata=_HANDOFF), entradas=entradas, sales=[],
                            opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["google:qualified:G1"]


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
    assert rows == []


def test_horario_sem_fuso_nao_derruba_a_varredura():
    # handoff.at sem fuso (gravação antiga/manual) é lido como UTC em vez de estourar
    # TypeError na comparação com datetimes com fuso.
    naive = (CLICK + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    lead = _lead(metadata={"handoff": {"at": naive, "motivo": "ok"}})
    rows = build_candidates(lead=lead, entradas=ENTRADAS, sales=[], opportunity_at=None, values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:qualified:C1"]
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
        "ad_conversion_values": [{"segment": "atacado", "stage": "qualified", "value": 80}],
        "lead_events": [{"lead_id": "L1", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C1"}}],
        "leads": [_lead(metadata={"handoff": {"at": (CLICK + timedelta(hours=1)).isoformat(), "motivo": "ok"}})],
        "sales": [], "quotes": [],
    }
    upserts, log = [], []
    monkeypatch.setattr(sweep_mod, "get_supabase", lambda: _fake_sb(tables, upserts, log))
    n = sweep_mod.run_sweep(now=NOW)
    assert n >= 1
    rows, kw = upserts[0]
    assert kw == {"on_conflict": "dedupe_key", "ignore_duplicates": True}
    assert any(r["dedupe_key"] == "meta:qualified:C1" and r["value"] == 80.0 for r in rows)
    # todas as linhas de um upsert em lote precisam das MESMAS chaves (PostgREST usa ?columns=)
    assert len({tuple(sorted(r)) for r in rows}) == 1
    # a hora da venda depende de created_at (venda do mesmo dia)
    sel = [a[0] for (t, attr, a, _k) in log if t == "sales" and attr == "select"]
    assert sel and "created_at" in sel[0].split(",")


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


def test_sweep_usa_o_paginador_compartilhado():
    from app.db.paginacao import paginar
    assert sweep_mod.paginar is paginar


def test_upsert_que_falha_num_bloco_nao_derruba_os_outros(monkeypatch, caplog):
    """Um bloco de 200 leads com upsert recusado (timeout, linha ruim) não pode impedir os blocos
    seguintes de entrar na fila."""
    ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(450)]
    h = {"at": (CLICK + timedelta(hours=1)).isoformat(), "motivo": "ok"}
    tables = {"lead_events": [{"lead_id": i, "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                               "metadata": {"ctwa_clid": f"C{n}"}} for n, i in enumerate(ids)],
              "leads": [_lead(id=i, ctwa_clid=f"C{n}", metadata={"handoff": h}) for n, i in enumerate(ids)],
              "sales": [], "quotes": [], "ad_conversion_values": []}
    upserts, log = [], []
    chamadas = [0]

    def _sb():
        sb = _fake_sb(tables, upserts, log)
        orig = sb.table.side_effect

        def _table(name):
            if name != "ad_conversions":
                return orig(name)
            q = MagicMock()

            def _up(rows, **kw):
                chamadas[0] += 1
                if chamadas[0] == 1:
                    raise RuntimeError("statement timeout")
                upserts.append((rows, kw))
                return MagicMock(data=rows)
            q.upsert.side_effect = _up
            return q
        sb.table.side_effect = _table
        return sb
    monkeypatch.setattr(sweep_mod, "get_supabase", _sb)
    with caplog.at_level("ERROR"):
        total = sweep_mod.run_sweep(now=NOW)
    assert chamadas[0] == 3
    assert [len(rows) for rows, _ in upserts] == [200, 50]
    assert total == 250
    assert any("falha no upsert" in r.getMessage() for r in caplog.records)


def test_venda_sem_valor_nao_entra(caplog):
    """Purchase sem valor ensinaria venda de R$ 0 ao algoritmo: fica fora (e avisa no log)."""
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": None,
              "status": "registrada"},
             {"id": "S2", "lead_id": "L1", "sold_at": (CLICK + timedelta(days=1)).isoformat(), "value": 50,
              "status": "registrada"}]
    with caplog.at_level("WARNING"):
        rows = build_candidates(lead=_lead(), entradas=ENTRADAS, sales=sales, opportunity_at=None,
                                values=VALUES, now=NOW)
    assert _keys(rows) == ["meta:purchase:S2"]
    assert any("S1" in r.getMessage() for r in caplog.records)


def test_um_lead_quebrado_nao_derruba_a_varredura(monkeypatch):
    tables = {
        "ad_conversion_values": [],
        "lead_events": [{"lead_id": "L1", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C1"}},
                        {"lead_id": "L2", "event_type": "entrada", "occurred_at": CLICK.isoformat(),
                         "metadata": {"ctwa_clid": "C9"}}],
        "leads": [_lead(id="L2", ctwa_clid="C9"),
                  _lead(metadata={"handoff": {"at": (CLICK + timedelta(hours=1)).isoformat(), "motivo": "ok"}})],
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
    assert keys == ["meta:qualified:C1"]
