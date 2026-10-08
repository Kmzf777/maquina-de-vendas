from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from scripts.conversoes import calcular_valores as cv
from scripts.conversoes.calcular_valores import propor_valores

T = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_valor_e_receita_em_30_dias_dividida_pelos_leads_da_etapa():
    # 4 leads atacado chegaram a "qualified"; 1 comprou 1000 em 10 dias, 1 comprou kit 120 em 40 dias (fora)
    marcos = [{"lead_id": f"L{i}", "segment": "atacado", "stage": "qualified", "at": T} for i in range(4)]
    vendas = [
        {"lead_id": "L0", "sold_at": T + timedelta(days=10), "value": 1000.0, "kit": False},
        {"lead_id": "L1", "sold_at": T + timedelta(days=40), "value": 120.0, "kit": True},
    ]
    p = propor_valores(marcos, vendas)
    cel = p[("atacado", "qualified")]
    assert cel["n"] == 4
    assert cel["valor"] == 250.0
    assert cel["receita_kit"] == 0.0 and cel["receita_nao_kit"] == 1000.0
    assert cel["pouco_dado"] is True  # n < 20


# ── marcos por lead ─────────────────────────────────────────────────────────
LEAD = {"id": "L1", "stage": "atacado", "ja_era_cliente": None, "metadata": {}, "created_at": T.isoformat(),
        "ctwa_clid": None, "gclid": None, "gbraid": None, "wbraid": None}


def _stages(marcos):
    return sorted((m["stage"], m["at"]) for m in marcos)


def test_lead_so_conta_quem_tem_clique_google():
    """Só o Google recebe a etapa `lead`: o valor dela é a receita de quem clicou no Google."""
    meta = [{"lead_id": "L1", "occurred_at": T.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    assert cv.marcos_do_lead(LEAD, meta) == []
    google = [{"lead_id": "L1", "occurred_at": (T + timedelta(days=2)).isoformat(), "metadata": {"gbraid": "B1"}}]
    marcos = cv.marcos_do_lead(LEAD, meta + google)
    # o marco `lead` é o 1º clique GOOGLE, não o 1º clique de qualquer plataforma
    assert _stages(marcos) == [("lead", T + timedelta(days=2))]
    assert marcos[0]["segment"] == "atacado"


def test_qualificado_vale_para_clique_de_qualquer_plataforma():
    h = {"at": (T + timedelta(hours=3)).isoformat(), "motivo": "lead qualificado"}
    meta = [{"lead_id": "L1", "occurred_at": T.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    assert _stages(cv.marcos_do_lead({**LEAD, "metadata": {"handoff": h}}, meta)) == \
        [("qualified", T + timedelta(hours=3))]


def test_entradas_paginadas_em_ordem_estavel():
    log = []

    class Q:
        def __getattr__(self, n):
            def call(*a, **k):
                log.append((n, a))
                return self
            return call

        def execute(self):
            return MagicMock(data=[])

    sb = MagicMock()
    sb.table.side_effect = lambda n: Q()
    cv._carregar(sb, T)
    nomes = [n for n, _a in log]
    assert ("order", ("id",)) in log
    assert nomes.index("order") < nomes.index("range")


class _Tab:
    """Tabela falsa: aplica `in_`, fatia por `.range()` e registra as chamadas."""

    def __init__(self, nome, linhas, log):
        self.nome, self.linhas, self.log = nome, list(linhas), log

    def __getattr__(self, n):
        def call(*a, **k):
            self.log.append((self.nome, n, a))
            if n == "in_":
                col, vals = a
                vs = set(vals)
                self.linhas = [r for r in self.linhas if r.get(col) in vs]
            if n == "range":
                self.linhas = self.linhas[a[0]:a[1] + 1]
            return self
        return call

    def execute(self):
        return MagicMock(data=self.linhas)


def test_vendas_e_itens_paginados_e_em_blocos_de_200():
    """Um bloco de 200 leads pode ter mais de 1000 vendas (teto do PostgREST) e o `.in_()` dos
    itens com milhares de ids estoura a URL: vendas/leads paginados, itens em blocos de 200."""
    leads = [{"id": f"L{i:03d}", "stage": "atacado", "metadata": {}, "created_at": T.isoformat()} for i in range(3)]
    entradas = [{"lead_id": l["id"], "occurred_at": T.isoformat(), "metadata": {"gclid": f"G{l['id']}"}} for l in leads]
    vendas = [{"id": f"S{i:04d}", "lead_id": "L000", "sold_at": (T + timedelta(days=1)).isoformat(), "value": 1,
               "status": "registrada"} for i in range(1300)]
    tabelas = {"lead_events": entradas, "leads": leads, "sales": vendas, "sale_items": []}
    log = []
    sb = MagicMock()
    sb.table.side_effect = lambda n: _Tab(n, tabelas[n], log)
    marcos, vs = cv._carregar(sb, T + timedelta(days=2))
    assert len(vs) == 1300
    itens = [len(a[1]) for (t, n, a) in log if t == "sale_items" and n == "in_"]
    assert itens and max(itens) <= 200 and sum(itens) == 1300
    for t in ("sales", "leads"):
        chamadas = [n for (tt, n, _a) in log if tt == t]
        assert "order" in chamadas and "range" in chamadas, t
