from typing import Any

from app.db.supabase import get_supabase


def get_or_create_lead(phone: str, name: str | None = None) -> dict[str, Any]:
    """Get or create a global lead by phone. Updates name if not yet set."""
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()

    if result.data:
        lead = result.data[0]
        if name and not lead.get("name"):
            result = sb.table("leads").update({"name": name}).eq("id", lead["id"]).execute()
            return result.data[0]
        return lead

    new_lead = {"phone": phone}
    if name:
        new_lead["name"] = name
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def get_lead(lead_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).single().execute()
    return result.data
