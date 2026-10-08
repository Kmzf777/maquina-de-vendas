from datetime import datetime, timedelta, timezone

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
