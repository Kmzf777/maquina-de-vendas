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
