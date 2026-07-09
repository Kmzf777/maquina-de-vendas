from datetime import datetime, timezone
from app.automation import engine


def test_window_rejects_weekend_when_skip_weekends():
    # 2026-07-11 is a Saturday; 12:00 BRT = 15:00 UTC.
    sat = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)
    assert engine._is_within_window(sat, 7, 18, skip_weekends=True) is False
    assert engine._is_within_window(sat, 7, 18, skip_weekends=False) is True
