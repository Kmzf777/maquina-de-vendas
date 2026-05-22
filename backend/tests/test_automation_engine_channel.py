# backend/tests/test_automation_engine_channel.py
import pytest
from unittest.mock import patch, MagicMock
from app.automation.engine import _resolve_channel


class TestResolveChannel:
    def test_node_channel_takes_priority(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "ch-node"}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            result = _resolve_channel(
                node_cfg={"channel_id": "ch-node"},
                campaign={"channel_id": "ch-campaign"},
            )
        assert result["id"] == "ch-node"

    def test_falls_back_to_campaign_channel(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "ch-campaign"}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            result = _resolve_channel(
                node_cfg={},
                campaign={"channel_id": "ch-campaign"},
            )
        assert result["id"] == "ch-campaign"

    def test_raises_when_no_channel(self):
        with pytest.raises(ValueError, match="Nenhum canal"):
            _resolve_channel(node_cfg={}, campaign={})
