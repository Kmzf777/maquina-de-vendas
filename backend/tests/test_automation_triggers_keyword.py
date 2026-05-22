import pytest
from unittest.mock import patch, MagicMock
from app.automation.triggers import _match_keyword_campaigns


class TestKeywordMatching:
    def test_matches_when_message_contains_keyword(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço", "valor"]},
            }
        ]
        with patch("app.automation.triggers.get_supabase", return_value=sb):
            result = _match_keyword_campaigns(message_body="Qual o PREÇO disso?")
        assert "camp1" in result

    def test_no_match_when_keyword_absent(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço"]},
            }
        ]
        with patch("app.automation.triggers.get_supabase", return_value=sb):
            result = _match_keyword_campaigns(message_body="Olá tudo bem")
        assert result == []
