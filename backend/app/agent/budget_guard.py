"""Trava de orçamento diário (kill-switch) para chamadas ao LLM.

Protege contra fuga financeira: se o gasto acumulado do dia (UTC) em `token_usage`
ultrapassar o teto configurado, novas chamadas ao LLM são bloqueadas. O orchestrator
converte esse bloqueio no MESMO fallback do llm_down (encaminhar_humano ao João), então
o lead nunca é fantasmado — só deixa de queimar cota.

Configuração (env):
    LLM_DAILY_COST_LIMIT_USD   teto de custo/dia em USD. Ausente/0 = DESLIGADO (default seguro).

Fonte de verdade: soma de `token_usage.total_cost` do dia corrente (UTC). Cache in-process
curto (_CACHE_TTL_SECS) evita uma query por chamada. FAIL-OPEN: qualquer erro de leitura
NÃO bloqueia — nunca derrubamos o atendimento por causa do medidor.

Observação: como `completion_tokens` agora inclui os thoughts_token_count (gemini_native),
`total_cost` passou a refletir o custo de output real, tornando este teto mais fiel.
"""
import logging
import os
import time
from datetime import datetime, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_CACHE_TTL_SECS = 30
_cache: dict = {"day": None, "spend": 0.0, "at": 0.0}


def daily_cost_limit_usd() -> float:
    """Teto diário em USD lido do env. <= 0 (ou inválido) desliga o kill-switch."""
    try:
        return float(os.environ.get("LLM_DAILY_COST_LIMIT_USD", "0") or 0)
    except (TypeError, ValueError):
        return 0.0


def _today_utc() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def today_spend_usd(force: bool = False) -> float:
    """Gasto do dia (UTC) somado de token_usage.total_cost, com cache curto. Fail-open → 0.0."""
    day, start = _today_utc()
    now = time.time()
    if not force and _cache["day"] == day and (now - _cache["at"]) < _CACHE_TTL_SECS:
        return _cache["spend"]
    try:
        sb = get_supabase()
        res = sb.table("token_usage").select("total_cost").gte("created_at", start).execute()
        spend = sum(float(r.get("total_cost") or 0) for r in (res.data or []))
    except Exception as exc:  # fail-open: medidor nunca bloqueia atendimento
        logger.warning("[BUDGET] falha ao ler gasto do dia — fail-open: %s", exc)
        return 0.0
    _cache.update(day=day, spend=spend, at=now)
    return spend


def is_exceeded() -> bool:
    """True se o kill-switch está ligado (limite > 0) E o gasto do dia atingiu o teto."""
    limit = daily_cost_limit_usd()
    if limit <= 0:
        return False  # desligado — caminho quente sai sem tocar no banco
    spend = today_spend_usd()
    if spend >= limit:
        logger.critical(
            "[BUDGET] KILL-SWITCH ATIVADO — gasto do dia US$%.2f >= teto US$%.2f. "
            "Bloqueando chamadas ao LLM (fallback handoff) ate a virada do dia (UTC).",
            spend, limit,
        )
        return True
    return False
