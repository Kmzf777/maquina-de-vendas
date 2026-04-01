from app.db.supabase import get_supabase


def get_agent_profile(profile_id: str) -> dict:
    sb = get_supabase()
    return (
        sb.table("agent_profiles")
        .select("*")
        .eq("id", profile_id)
        .single()
        .execute()
        .data
    )
