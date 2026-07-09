from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


async def test_send_skipped_when_last_sent_node_matches_current():
    from app.automation import engine
    node = {"id": "n-send", "type": "send", "config": {"template_name": "t"}, "next_node_id": "n2"}
    enrollment = {"id": "e1", "lead_id": "l1", "last_sent_node_id": "n-send",
                  "campaign_nodes": node, "leads": {"id": "l1", "phone": "5511999999999", "ai_enabled": True}}
    campaign = {"status": "active", "channel_id": "ch1"}
    enrollment["campaigns"] = campaign

    send_node = AsyncMock()
    with patch("app.campaigns.worker._execute_send_node", send_node), \
         patch.object(engine, "check_frequency_cap", return_value=True), \
         patch.object(engine, "_is_within_window", return_value=True), \
         patch.object(engine, "_conversation_followup_disabled", return_value=False), \
         patch.object(engine, "record_daily_send"), \
         patch.object(engine, "_update") as upd:
        await engine._process_one(enrollment, datetime.now(timezone.utc))

    send_node.assert_not_awaited()          # idempotent skip
    assert upd.called                       # still advanced past the node
