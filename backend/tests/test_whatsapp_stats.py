import pytest
from unittest.mock import MagicMock, patch
from datetime import date


def _make_sb(webhook_rows: list, template_rows: list) -> MagicMock:
    """Helper to build a Supabase mock that routes by table name."""
    sb = MagicMock()

    def table_router(name: str):
        t = MagicMock()
        if name == "meta_webhook_logs":
            (
                t.select.return_value
                .eq.return_value
                .eq.return_value
                .eq.return_value
                .gte.return_value
                .lt.return_value
                .limit.return_value
                .execute.return_value
                .data
            ) = webhook_rows
        elif name == "message_templates":
            t.select.return_value.in_.return_value.execute.return_value.data = template_rows
        return t

    sb.table.side_effect = table_router
    return sb


# ---------------------------------------------------------------------------
# get_whatsapp_costs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whatsapp_costs_empty():
    sb = _make_sb(webhook_rows=[], template_rows=[])
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 0
    assert result["utility_count"] == 0
    assert result["total_whatsapp_cost"] == 0.0


@pytest.mark.asyncio
async def test_whatsapp_costs_marketing():
    webhook_rows = [
        {"payload": {"template": {"name": "campanha_maio"}}, "received_at": "2026-05-01T10:00:00"},
        {"payload": {"template": {"name": "campanha_maio"}}, "received_at": "2026-05-02T10:00:00"},
    ]
    template_rows = [{"name": "campanha_maio", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 2
    assert result["marketing_cost"] == round(2 * 0.0617, 4)
    assert result["utility_count"] == 0
    assert result["utility_cost"] == 0.0


@pytest.mark.asyncio
async def test_whatsapp_costs_utility():
    webhook_rows = [
        {"payload": {"template": {"name": "followup_util"}}, "received_at": "2026-05-01T10:00:00"},
    ]
    template_rows = [{"name": "followup_util", "category": "UTILITY"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["utility_count"] == 1
    assert result["utility_cost"] == round(1 * 0.0067, 4)
    assert result["marketing_count"] == 0


@pytest.mark.asyncio
async def test_whatsapp_costs_unknown_template_fallback_marketing():
    """Template ausente em message_templates -> fallback MARKETING."""
    webhook_rows = [
        {"payload": {"template": {"name": "deleted_template"}}, "received_at": "2026-05-01T10:00:00"},
    ]
    sb = _make_sb(webhook_rows=webhook_rows, template_rows=[])
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_costs
        result = await get_whatsapp_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 7))
    assert result["marketing_count"] == 1
    assert result["utility_count"] == 0


# ---------------------------------------------------------------------------
# get_whatsapp_daily_costs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whatsapp_daily_groups_by_date():
    webhook_rows = [
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T08:00:00"},
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T10:00:00"},
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-02T09:00:00"},
    ]
    template_rows = [{"name": "camp", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_daily_costs
        result = await get_whatsapp_daily_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 3))

    data = result["data"]
    assert len(data) == 2
    may1 = next(d for d in data if d["date"] == "2026-05-01")
    may2 = next(d for d in data if d["date"] == "2026-05-02")
    assert may1["marketing_cost"] == round(2 * 0.0617, 4)
    assert may2["marketing_cost"] == round(1 * 0.0617, 4)
    assert may1["utility_cost"] == 0.0
    assert may1["total"] == may1["marketing_cost"] + may1["utility_cost"]


@pytest.mark.asyncio
async def test_whatsapp_daily_fills_zero_gaps():
    """Dias sem mensagens aparecem com zeros."""
    webhook_rows = [
        {"payload": {"template": {"name": "camp"}}, "received_at": "2026-05-01T08:00:00"},
    ]
    template_rows = [{"name": "camp", "category": "MARKETING"}]
    sb = _make_sb(webhook_rows, template_rows)
    with patch("app.stats.router.get_supabase", return_value=sb):
        from app.stats.router import get_whatsapp_daily_costs
        result = await get_whatsapp_daily_costs(start_date=date(2026, 5, 1), end_date=date(2026, 5, 4))

    data = result["data"]
    assert len(data) == 3
    may3 = next(d for d in data if d["date"] == "2026-05-03")
    assert may3["marketing_cost"] == 0.0
    assert may3["utility_cost"] == 0.0
    assert may3["total"] == 0.0
