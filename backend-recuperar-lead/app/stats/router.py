from fastapi import APIRouter, Query
from datetime import date, timedelta
from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/costs")
async def get_costs(
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    model: str | None = None,
    lead_id: str | None = None,
):
    """Get aggregated cost metrics for the given filters."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    query = (
        sb.table("token_usage")
        .select("total_cost, prompt_tokens, completion_tokens, lead_id")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
        .limit(10000)
    )

    if stage:
        query = query.eq("stage", stage)
    if model:
        query = query.eq("model", model)
    if lead_id:
        query = query.eq("lead_id", lead_id)

    result = query.execute()
    rows = result.data

    total_cost = sum(float(r["total_cost"]) for r in rows)
    total_calls = len(rows)
    total_prompt_tokens = sum(r["prompt_tokens"] for r in rows)
    total_completion_tokens = sum(r["completion_tokens"] for r in rows)
    unique_leads = len(set(r["lead_id"] for r in rows if r["lead_id"]))
    avg_cost_per_lead = total_cost / unique_leads if unique_leads > 0 else 0

    return {
        "total_cost": round(total_cost, 6),
        "total_calls": total_calls,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "unique_leads": unique_leads,
        "avg_cost_per_lead": round(avg_cost_per_lead, 6),
    }


@router.get("/costs/daily")
async def get_daily_costs(
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    model: str | None = None,
):
    """Get costs grouped by day for chart rendering."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    query = (
        sb.table("token_usage")
        .select("total_cost, created_at")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
        .limit(10000)
    )

    if stage:
        query = query.eq("stage", stage)
    if model:
        query = query.eq("model", model)

    result = query.execute()

    # Group by date
    daily: dict[str, float] = {}
    for row in result.data:
        day = row["created_at"][:10]  # YYYY-MM-DD
        daily[day] = daily.get(day, 0) + float(row["total_cost"])

    # Fill gaps with zeros
    data = []
    current = start_date
    while current < end_date:
        day_str = current.isoformat()
        data.append({"date": day_str, "cost": round(daily.get(day_str, 0), 6)})
        current += timedelta(days=1)

    return {"data": data}


@router.get("/costs/breakdown")
async def get_cost_breakdown(
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str = Query("stage", pattern="^(stage|model|lead)$"),
):
    """Get costs grouped by stage, model, or lead."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    select_fields = "total_cost, prompt_tokens, completion_tokens, stage, model, lead_id"
    query = (
        sb.table("token_usage")
        .select(select_fields)
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
        .limit(10000)
    )

    result = query.execute()

    groups: dict[str, dict] = {}
    for row in result.data:
        if group_by == "lead":
            key = row["lead_id"] or "unknown"
        else:
            key = row[group_by]

        if key not in groups:
            groups[key] = {"key": key, "cost": 0, "calls": 0, "tokens": 0}

        groups[key]["cost"] += float(row["total_cost"])
        groups[key]["calls"] += 1
        groups[key]["tokens"] += row["prompt_tokens"] + row["completion_tokens"]

    data = sorted(groups.values(), key=lambda x: x["cost"], reverse=True)

    # Round costs
    for item in data:
        item["cost"] = round(item["cost"], 6)

    return {"data": data}


@router.get("/costs/top-leads")
async def get_top_leads(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(20, le=100),
):
    """Get top leads by cost with lead details."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    result = (
        sb.table("token_usage")
        .select("total_cost, prompt_tokens, completion_tokens, lead_id, stage")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
        .limit(10000)
        .execute()
    )

    # Aggregate by lead
    leads_data: dict[str, dict] = {}
    for row in result.data:
        lid = row["lead_id"]
        if not lid:
            continue
        if lid not in leads_data:
            leads_data[lid] = {"lead_id": lid, "cost": 0, "calls": 0, "tokens": 0, "stage": row["stage"]}
        leads_data[lid]["cost"] += float(row["total_cost"])
        leads_data[lid]["calls"] += 1
        leads_data[lid]["tokens"] += row["prompt_tokens"] + row["completion_tokens"]
        leads_data[lid]["stage"] = row["stage"]  # latest stage

    sorted_leads = sorted(leads_data.values(), key=lambda x: x["cost"], reverse=True)[:limit]

    # Fetch lead names
    if sorted_leads:
        lead_ids = [l["lead_id"] for l in sorted_leads]
        lead_info = sb.table("leads").select("id, name, phone").in_("id", lead_ids).execute()
        lead_map = {l["id"]: l for l in lead_info.data}

        for item in sorted_leads:
            info = lead_map.get(item["lead_id"], {})
            item["name"] = info.get("name") or info.get("phone", "Desconhecido")
            item["phone"] = info.get("phone", "")
            item["cost"] = round(item["cost"], 6)

    return {"data": sorted_leads}
