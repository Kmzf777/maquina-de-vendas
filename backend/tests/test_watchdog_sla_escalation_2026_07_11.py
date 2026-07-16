"""Escalonamento por ACÚMULO do Check 5 (`handoff_sla_escalation`) — 11/07/2026.

Contexto (go/no-go do disparo em massa frios, 11/07): o Check 5 detecta e alerta,
mas em `warning` — 50 alertas em 3 dias (49 não resolvidos) sem NENHUM ping ativo
ao operador, porque `warning` não despacha WhatsApp (alerts/_notify_external).
Uma fila em pé com >= HANDOFF_SLA_ESCALATION_THRESHOLD conversas violadas é
incidente de plantão, não ruído: vira UM alerta `critical` (Sentry + WhatsApp do
admin via T2), com dedup global de HANDOFF_SLA_ESCALATION_DEDUP_HOURS enquanto a
fila não baixar. Os breaches individuais continuam `warning` (sem spam por lead).

Reusa FakeSupabase/seeds de test_watchdog_handoff_sla_2026_07_03 (mesmo padrão de
reuso aditivo daquele arquivo).
"""
from datetime import datetime, timedelta, timezone

from app.watchdog import service as W
from app.watchdog.service import check_handoff_sla

from tests.test_watchdog_checks_2026_07_02 import _iso
from tests.test_watchdog_handoff_sla_2026_07_03 import (
    _fake_db,
    _local,
    _seed_conversation_check5,
    _seed_sla_alert,
)


def _seed_n_violations(fake, now, n):
    for i in range(n):
        _seed_conversation_check5(
            fake, f"conv-{i}",
            last_customer_message_at=now - timedelta(minutes=30 + i),
            last_seller_response_at=None,
            name=f"Lead{i}",
        )


def _alerts_of(fake, alert_type):
    return [a for a in fake.tables["system_alerts"] if a["type"] == alert_type]


def test_acumulo_no_limiar_dispara_escalation_critical(monkeypatch):
    """Fila com THRESHOLD conversas violadas → 1 `handoff_sla_escalation` critical
    (metadata.count = fila total), ADITIVO ao breach warning individual."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 11, 14, 0)
    _seed_n_violations(fake, now, W.HANDOFF_SLA_ESCALATION_THRESHOLD)

    result = check_handoff_sla(now)

    assert result == W.HANDOFF_SLA_ESCALATION_THRESHOLD
    escalations = _alerts_of(fake, "handoff_sla_escalation")
    assert len(escalations) == 1
    assert escalations[0]["severity"] == "critical"
    assert escalations[0]["metadata"]["count"] == W.HANDOFF_SLA_ESCALATION_THRESHOLD
    assert len(escalations[0]["metadata"]["conversation_ids"]) == W.HANDOFF_SLA_ESCALATION_THRESHOLD
    # o alerta individual continua existindo — escalation não o substitui
    assert len(_alerts_of(fake, "handoff_sla_breach")) == 1


def test_abaixo_do_limiar_nao_escala(monkeypatch):
    """THRESHOLD-1 violações: breach warning normal, ZERO escalation."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 11, 14, 0)
    _seed_n_violations(fake, now, W.HANDOFF_SLA_ESCALATION_THRESHOLD - 1)

    check_handoff_sla(now)

    assert _alerts_of(fake, "handoff_sla_escalation") == []
    assert len(_alerts_of(fake, "handoff_sla_breach")) == 1


def test_escalation_dedup_global_nao_repete_dentro_da_janela(monkeypatch):
    """Escalation não-resolvida criada há 30min (< DEDUP_HOURS) → não re-escala
    (mesmo contrato de `_alert_recently_fired` dos Checks 1/3/6)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 11, 14, 0)
    # `_alert_recently_fired` usa o relógio REAL (não recebe `now`) — o seed do
    # dedup precisa ser relativo a ele. 30min < DEDUP_HOURS=2h vale sempre,
    # independente de quando a suíte roda (determinístico).
    fake.tables["system_alerts"].append({
        "type": "handoff_sla_escalation",
        "resolved": False,
        "created_at": _iso(datetime.now(timezone.utc) - timedelta(minutes=30)),
        "metadata": {},
    })
    _seed_n_violations(fake, now, W.HANDOFF_SLA_ESCALATION_THRESHOLD)

    check_handoff_sla(now)

    assert len(_alerts_of(fake, "handoff_sla_escalation")) == 1  # só o seed


def test_escalation_conta_a_fila_em_pe_mesmo_sem_breach_novo(monkeypatch):
    """Acúmulo mede a fila EM PÉ: com todas as conversas já cobertas pelo dedup
    POR CONVERSA do breach (nenhum breach novo é inserido), a escalation dispara
    mesmo assim — é o drumbeat que o caso real de 11/07 (49 warnings ignorados)
    não tinha."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 11, 14, 0)
    n = W.HANDOFF_SLA_ESCALATION_THRESHOLD
    _seed_n_violations(fake, now, n)
    _seed_sla_alert(fake, [f"conv-{i}" for i in range(n)], now - timedelta(minutes=40))

    result = check_handoff_sla(now)

    assert result == n
    assert len(_alerts_of(fake, "handoff_sla_breach")) == 1  # só o seed — nenhum novo
    escalations = _alerts_of(fake, "handoff_sla_escalation")
    assert len(escalations) == 1
    assert escalations[0]["metadata"]["count"] == n
