import pytest
from datetime import datetime, timezone, timedelta
from app.automation.retry import calculate_next_retry

NOW = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)


class TestCalculateNextRetry:
    def test_first_retry_is_1h(self):
        next_at, count, final = calculate_next_retry(0, NOW)
        assert next_at == NOW + timedelta(hours=1)
        assert count == 1
        assert final is False

    def test_second_retry_is_4h(self):
        next_at, count, final = calculate_next_retry(1, NOW)
        assert next_at == NOW + timedelta(hours=4)
        assert count == 2
        assert final is False

    def test_third_retry_is_24h(self):
        next_at, count, final = calculate_next_retry(2, NOW)
        assert next_at == NOW + timedelta(hours=24)
        assert count == 3
        assert final is False

    def test_after_max_retries_is_final(self):
        _, _, final = calculate_next_retry(3, NOW)
        assert final is True

    def test_after_max_retries_count_unchanged(self):
        _, count, _ = calculate_next_retry(3, NOW)
        assert count == 3
