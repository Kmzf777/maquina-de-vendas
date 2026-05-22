import pytest
from unittest.mock import patch, MagicMock
from app.automation.triggers import fire_trigger


class TestKeywordReceivedTrigger:
    @pytest.mark.asyncio
    async def test_enrolls_when_keyword_matches(self):
        active_trigger_nodes = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "next_node_id": "node2",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço", "valor"]},
            }
        ]
        with patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=active_trigger_nodes), \
             patch("app.automation.triggers.is_already_enrolled", return_value=False), \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            await fire_trigger("message_received", lead_id="lead1", data={"body": "Qual o PREÇO disso?"})
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["campaign_id"] == "camp1"
        assert kwargs["lead_id"] == "lead1"
        assert kwargs["current_node_id"] == "node2"

    @pytest.mark.asyncio
    async def test_does_not_enroll_when_keyword_absent(self):
        active_trigger_nodes = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "next_node_id": "node2",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço"]},
            }
        ]
        with patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=active_trigger_nodes), \
             patch("app.automation.triggers.is_already_enrolled", return_value=False), \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            await fire_trigger("message_received", lead_id="lead1", data={"body": "Olá tudo bem"})
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_via_get_campaigns_with_trigger_type(self):
        """get_campaigns_with_trigger_type already filters by env_tag and status=active.
        This test confirms fire_trigger relies on it (not a raw query)."""
        with patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]) as mock_get, \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            await fire_trigger("message_received", lead_id="lead1", data={"body": "preço"})
        mock_get.assert_called_once_with("keyword_received")
        mock_create.assert_not_called()
