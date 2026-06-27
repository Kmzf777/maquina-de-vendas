from datetime import datetime, timezone, timedelta
import importlib


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_build_touch_jobs_creates_four_sequential_jobs():
    from app.follow_up.cadence import build_touch_jobs, CADENCE
    assert len(CADENCE) == 4
    # Monday 12:00 UTC = 09:00 BRT (inside window)
    now = _utc(2026, 6, 29, 12, 0)
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    assert [j["sequence"] for j in jobs] == [1, 2, 3, 4]
    assert all(j["status"] == "pending" for j in jobs)
    assert all(j["env_tag"] == "dev" for j in jobs)
    assert all(j["conversation_id"] == "conv-1" for j in jobs)
    # objectives carried in metadata, in order
    assert [j["metadata"]["objetivo"] for j in jobs] == [
        "reengajar", "reforco_valor", "prova_social", "ultima_chamada"
    ]
    # contexto mirrors objective (for reopen reuse), objective_prompt present
    for j in jobs:
        assert j["metadata"]["contexto"] == j["metadata"]["objetivo"]
        assert j["metadata"]["objective_prompt"]


def test_build_touch_jobs_fire_at_monotonic_and_in_business_window():
    from app.follow_up.cadence import build_touch_jobs, MIN_GAP
    from app.follow_up.service import is_within_business_window
    # Friday 23:00 BRT = Saturday 02:00 UTC — the collision scenario (R2)
    now = _utc(2026, 6, 27, 2, 0)  # Sat 02:00 UTC = Fri 23:00 BRT
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    fires = [datetime.fromisoformat(j["fire_at"]) for j in jobs]
    # strictly increasing with >= MIN_GAP spacing, all inside business window
    for earlier, later in zip(fires, fires[1:]):
        assert later >= earlier + MIN_GAP
    for f in fires:
        assert is_within_business_window(f)


def test_build_touch_jobs_t1_jitter_within_range():
    from app.follow_up.cadence import build_touch_jobs

    class _FixedRng:
        def randint(self, a, b):
            return a  # lower bound -> 90 min
    now = _utc(2026, 6, 29, 12, 0)  # Mon 09:00 BRT
    jobs = build_touch_jobs(now, "c", "l", "ch", "dev", rng=_FixedRng())
    t1_fire = datetime.fromisoformat(jobs[0]["fire_at"])
    # 09:00 BRT + 90 min = 10:30 BRT = 13:30 UTC, still in window
    assert t1_fire == _utc(2026, 6, 29, 13, 30)
