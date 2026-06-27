"""Erro 3: lead frio (sem interesse) não recebe o T1 same-day — cadência começa no T2."""
from datetime import datetime, timezone


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_cold_start_skips_t1_same_day():
    from app.follow_up.cadence import build_touch_jobs
    now = _utc(2026, 6, 29, 12, 0)  # Mon 09:00 BRT
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev", warm=False)
    # T1 (sequence 1, same-day) suprimido — cadência começa no T2
    assert [j["sequence"] for j in jobs] == [2, 3, 4]
    assert [j["metadata"]["objetivo"] for j in jobs] == [
        "reforco_valor", "prova_social", "ultima_chamada"
    ]
    # nenhum job dispara no mesmo dia do agendamento (29/06)
    for j in jobs:
        fire = datetime.fromisoformat(j["fire_at"])
        assert fire.date() > now.date(), f"job seq={j['sequence']} disparou same-day ({fire})"


def test_warm_start_keeps_full_cadence_default_true():
    from app.follow_up.cadence import build_touch_jobs
    now = _utc(2026, 6, 29, 12, 0)
    # default (warm=True) preserva os 4 toques, T1 same-day
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    assert [j["sequence"] for j in jobs] == [1, 2, 3, 4]
    assert datetime.fromisoformat(jobs[0]["fire_at"]).date() == now.date()
