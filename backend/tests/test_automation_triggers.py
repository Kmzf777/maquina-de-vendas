import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from app.automation.triggers import _passes_filter, fire_trigger


class TestPassesFilter:
    def test_stage_enter_matches(self):
        assert _passes_filter("stage_enter", {"stage_filter": "negociacao"}, {"stage": "negociacao"}) is True

    def test_stage_enter_no_match(self):
        assert _passes_filter("stage_enter", {"stage_filter": "proposta"}, {"stage": "negociacao"}) is False

    def test_stage_enter_no_filter_passes_all(self):
        assert _passes_filter("stage_enter", {}, {"stage": "qualquer"}) is True

    def test_sale_created_min_value_passes(self):
        assert _passes_filter("sale_created", {"min_value": 100}, {"value": 200}) is True

    def test_sale_created_min_value_blocks(self):
        assert _passes_filter("sale_created", {"min_value": 300}, {"value": 200}) is False

    def test_sale_created_product_filter_passes(self):
        assert _passes_filter("sale_created", {"product_filter": "café"}, {"product": "Café Especial"}) is True

    def test_sale_created_product_filter_blocks(self):
        assert _passes_filter("sale_created", {"product_filter": "café"}, {"product": "Chá"}) is False

    def test_tag_added_matches(self):
        assert _passes_filter("tag_added", {"tag_name": "VIP"}, {"tag_name": "VIP"}) is True

    def test_deal_closed_lost_always_passes(self):
        assert _passes_filter("deal_closed_lost", {}, {}) is True


@pytest.mark.asyncio
async def test_fire_trigger_enrolls_matching_lead():
    trigger_node = {
        "campaign_id": "camp-1",
        "next_node_id": "node-1",
        "config": {"stage_filter": "negociacao"},
    }
    with (
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[trigger_node]),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await fire_trigger("stage_enter", "lead-1", {"stage": "negociacao"})
    mock_enroll.assert_called_once()


@pytest.mark.asyncio
async def test_fire_trigger_skips_already_enrolled():
    trigger_node = {
        "campaign_id": "camp-1",
        "next_node_id": "node-1",
        "config": {},
    }
    with (
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[trigger_node]),
        patch("app.automation.triggers.is_already_enrolled", return_value=True),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await fire_trigger("sale_created", "lead-1", {})
    mock_enroll.assert_not_called()
