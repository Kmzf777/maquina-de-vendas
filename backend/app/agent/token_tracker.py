import logging
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# In-memory cache for model pricing (refreshed per call to avoid stale data in long-running process)
_pricing_cache: dict[str, dict] = {}
_pricing_loaded = False


def _load_pricing():
    global _pricing_cache, _pricing_loaded
    try:
        sb = get_supabase()
        result = sb.table("model_pricing").select("*").execute()
        _pricing_cache = {row["model"]: row for row in result.data}
    except Exception as e:
        logger.warning(f"Could not load model pricing (table may not exist): {e}")
        _pricing_cache = {}
    _pricing_loaded = True


def get_model_pricing(model: str) -> dict | None:
    if not _pricing_loaded:
        _load_pricing()
    return _pricing_cache.get(model)


def refresh_pricing():
    """Force refresh pricing cache. Call after price updates."""
    global _pricing_loaded
    _pricing_loaded = False


# Tokens de prompt servidos pelo implicit caching do Gemini são cobrados a ~25% do preço
# de input (desconto de 75% anunciado p/ a família 2.5). Fator isolado em constante para
# auditoria/ajuste — se o provedor mudar o desconto, muda-se AQUI e nada mais.
CACHED_INPUT_PRICE_FACTOR = 0.25

# Colunas adicionadas pela migração 20260708 (supabase/migrations). O insert tenta o
# formato novo e, se o schema ainda não tiver as colunas (deploy antes da migração →
# PGRST204), re-insere no formato legado — a linha de contabilidade nunca se perde.
_NEW_USAGE_COLUMNS = ("thoughts_tokens", "cached_tokens")


def _is_unknown_column_error(exc: Exception) -> bool:
    msg = str(exc)
    return "PGRST204" in msg or any(col in msg for col in _NEW_USAGE_COLUMNS)


def track_token_usage(
    lead_id: str,
    stage: str,
    model: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
):
    """Record a single API call's token usage and cost.

    Args:
        lead_id: UUID of the lead
        stage: Agent stage at time of call
        model: Model name (e.g. 'gemini-2.5-flash')
        call_type: Free-form text (no DB enum/CHECK constraint). Values actually emitted
            today — verified via grep for `call_type=` across the repo; re-grep before
            adding a new one, 2026-07-08: 'response' (initial call and the main tool-loop's
            post-tool call, both in orchestrator.py run_agent), 'response_retry' (1st
            retry-on-empty rung and its Change B post-tool continuation), 'response_retry2'
            (2nd retry-on-empty rung, elevated temperature), 'response_loopguard' (text-only
            fallback after MAX_TOOL_ITERATIONS) — all in orchestrator.py; 'followup'
            (proactive re-engagement dispatch, follow_up/scheduler.py);
            'qualification_summary' (handoff briefing, summary.py); 'rolling_summary'
            (Dossiê do Lead, memory_manager.py); 'media_transcription' (áudio,
            buffer/processor.py). 'classification' / 'media_description' remain design-only
            (docs/superpowers/specs/2026-03-30-estatisticas-token-costs-design.md).
        prompt_tokens: Input tokens from response.usage
        completion_tokens: Output tokens from response.usage (JÁ incluem thinking — ver gemini_native)
        cached_tokens: Subconjunto de prompt_tokens servido pelo implicit caching do Gemini
            (usage.cached_tokens) — cobrado a CACHED_INPUT_PRICE_FACTOR do preço de input.
        reasoning_tokens: Tokens de thinking (usage.reasoning_tokens), persistidos à parte em
            thoughts_tokens só para observabilidade — o custo deles já está em completion_tokens.
    """
    pricing = get_model_pricing(model)

    if pricing:
        price_in = pricing["price_per_input_token"]
        price_out = pricing["price_per_output_token"]
    else:
        logger.warning(f"No pricing found for model {model}, using 0")
        price_in = 0
        price_out = 0

    # Nunca deixar a parte cheia ficar negativa se o provedor reportar cached > prompt.
    billable_cached = min(max(int(cached_tokens or 0), 0), max(int(prompt_tokens or 0), 0))
    full_price_prompt = max(int(prompt_tokens or 0), 0) - billable_cached

    # (total_cost_override removido em 12/07 — era código morto: zero call sites; todo
    # caminho de custo, inclusive transcrição, é token-based desde f5f7458.)
    total_cost = (
        full_price_prompt * float(price_in)
        + billable_cached * float(price_in) * CACHED_INPUT_PRICE_FACTOR
        + completion_tokens * float(price_out)
    )

    row = {
        "lead_id": lead_id,
        "stage": stage,
        "model": model,
        "call_type": call_type,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "thoughts_tokens": int(reasoning_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "price_per_input_token": float(price_in),
        "price_per_output_token": float(price_out),
        "total_cost": float(total_cost),
    }
    try:
        sb = get_supabase()
        try:
            sb.table("token_usage").insert(row).execute()
        except Exception as e:
            if not _is_unknown_column_error(e):
                raise
            # Schema ainda sem as colunas novas (deploy antes da migração 20260708):
            # re-insere no formato legado para não perder a linha de contabilidade.
            legacy = {k: v for k, v in row.items() if k not in _NEW_USAGE_COLUMNS}
            logger.warning(
                "token_usage sem colunas novas (%s) — gravando formato legado. Aplique a "
                "migração 20260708_token_usage_cache_cols. Erro: %s",
                ", ".join(_NEW_USAGE_COLUMNS), e,
            )
            sb.table("token_usage").insert(legacy).execute()
    except Exception as e:
        logger.error(f"Failed to track token usage: {e}")
