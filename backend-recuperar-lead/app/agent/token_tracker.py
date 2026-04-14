import logging
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# In-memory cache for model pricing (refreshed per call to avoid stale data in long-running process)
_pricing_cache: dict[str, dict] = {}
_pricing_loaded = False


def _load_pricing():
    global _pricing_cache, _pricing_loaded
    sb = get_supabase()
    result = sb.table("model_pricing").select("*").execute()
    _pricing_cache = {row["model"]: row for row in result.data}
    _pricing_loaded = True


def get_model_pricing(model: str) -> dict | None:
    if not _pricing_loaded:
        _load_pricing()
    return _pricing_cache.get(model)


def refresh_pricing():
    """Force refresh pricing cache. Call after price updates."""
    global _pricing_loaded
    _pricing_loaded = False


def track_token_usage(
    lead_id: str,
    stage: str,
    model: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_cost_override: float | None = None,
):
    """Record a single API call's token usage and cost.

    Args:
        lead_id: UUID of the lead
        stage: Agent stage at time of call
        model: Model name (e.g. 'gpt-4.1')
        call_type: One of 'classification', 'response', 'media_description', 'media_transcription'
        prompt_tokens: Input tokens from response.usage
        completion_tokens: Output tokens from response.usage
        total_cost_override: If set, use this instead of calculating from tokens (for Whisper)
    """
    pricing = get_model_pricing(model)

    if pricing:
        price_in = pricing["price_per_input_token"]
        price_out = pricing["price_per_output_token"]
    else:
        logger.warning(f"No pricing found for model {model}, using 0")
        price_in = 0
        price_out = 0

    if total_cost_override is not None:
        total_cost = total_cost_override
    else:
        total_cost = (prompt_tokens * float(price_in)) + (completion_tokens * float(price_out))

    try:
        sb = get_supabase()
        sb.table("token_usage").insert({
            "lead_id": lead_id,
            "stage": stage,
            "model": model,
            "call_type": call_type,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "price_per_input_token": float(price_in),
            "price_per_output_token": float(price_out),
            "total_cost": float(total_cost),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to track token usage: {e}")
