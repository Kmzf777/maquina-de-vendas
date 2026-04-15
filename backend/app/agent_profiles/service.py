from app.db.supabase import get_supabase


def get_agent_profile(profile_id: str) -> dict | None:
    sb = get_supabase()
    result = (
        sb.table("agent_profiles")
        .select("*")
        .eq("id", profile_id)
        .single()
        .execute()
    )
    return result.data
