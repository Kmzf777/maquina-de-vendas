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


def get_profile_id_by_prompt_key(prompt_key: str) -> str | None:
    """Resolve o agent_profile_id pela persona (prompt_key), env-agnostico.

    Evita hardcode de UUID que diverge entre bancos (prod x homolog). Retorna o id
    do primeiro profile com aquele prompt_key, ou None se nao houver (fail-open:
    o chamador cai no default do canal). Nunca levanta.
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("agent_profiles")
            .select("id")
            .eq("prompt_key", prompt_key)
            .limit(1)
            .execute()
        )
        return (result.data[0]["id"] if result.data else None)
    except Exception:
        return None
