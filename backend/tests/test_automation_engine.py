import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.automation.engine import check_frequency_cap, _compare

NOW = datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT


class TestCheckFrequencyCap:
    def test_no_sends_today_allows(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 1) is True

    def test_at_cap_blocks(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"count": 1}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 1) is False

    def test_below_cap_allows(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"count": 1}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 2) is True


class TestCompare:
    def test_gte(self):
        assert _compare(5, "gte", 3) is True
        assert _compare(2, "gte", 3) is False

    def test_lte(self):
        assert _compare(2, "lte", 3) is True
        assert _compare(5, "lte", 3) is False

    def test_eq(self):
        assert _compare(3, "eq", 3) is True
        assert _compare(4, "eq", 3) is False

    def test_unknown_operator_returns_false(self):
        assert _compare(5, "unknown", 3) is False
