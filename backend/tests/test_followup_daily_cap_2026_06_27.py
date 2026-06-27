"""Erro 2 (parte 2): cap de T1 same-day — um lead não recebe múltiplos toques no mesmo dia.

Produção (lead Johny): dois jobs standard seq=1 (same-day) enviados no mesmo dia porque cada
turno re-armava a cadência. A trava força warm=False se já houve toque same-day hoje.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import app.follow_up.service as svc


def _conv_exists(sb):
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"id": "conv-1"}])
    )


def test_already_touched_today_true_quando_ha_sent_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)  # 14h BRT
    sb = MagicMock()
    # query de jobs sent hoje retorna 1 linha
    (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
       .eq.return_value
       .gte.return_value.lt.return_value.limit.return_value.execute.return_value) = MagicMock(
        data=[{"id": "job-sent"}]
    )
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    assert svc._already_touched_today("conv-1", now) is True


def test_schedule_followup_forca_warm_false_se_ja_tocado_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)
    captured = {}

    def fake_build(now_, conv, lead, chan, env, warm=True):
        captured["warm"] = warm
        return []

    sb = MagicMock()
    _conv_exists(sb)
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    monkeypatch.setattr(svc, "_already_touched_today", lambda c, n: True)
    monkeypatch.setattr("app.follow_up.cadence.build_touch_jobs", fake_build)

    svc.schedule_followup("conv-1", "lead-1", "chan-1", warm=True)
    assert captured["warm"] is False  # cap: já tocou hoje → suprime T1 same-day


def test_schedule_followup_preserva_warm_true_sem_toque_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)
    captured = {}

    def fake_build(now_, conv, lead, chan, env, warm=True):
        captured["warm"] = warm
        return []

    sb = MagicMock()
    _conv_exists(sb)
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    monkeypatch.setattr(svc, "_already_touched_today", lambda c, n: False)
    monkeypatch.setattr("app.follow_up.cadence.build_touch_jobs", fake_build)

    svc.schedule_followup("conv-1", "lead-1", "chan-1", warm=True)
    assert captured["warm"] is True
