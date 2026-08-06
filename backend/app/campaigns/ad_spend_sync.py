"""Sync diário do investimento do Google Ads para a tabela ad_spend (upsert idempotente).

Env-gated (no-op sem credenciais) e fail-soft. Rodado pelo tick diário do worker
(app/worker/main.py::_ad_spend_sync_tick) e sob demanda pelo botão Atualizar do /trafego;
o script scripts/sync_google_ads_spend.py continua disponível para rodar manualmente."""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.campaigns.google_ads import fetch_campaign_spend, google_ads_enabled

logger = logging.getLogger(__name__)


async def sync_google_ads_spend(days: int = 30) -> int:
    """Busca o spend dos últimos `days` dias e faz upsert em ad_spend. Retorna nº de linhas."""
    if not google_ads_enabled():
        logger.info("ad_spend_sync: Google Ads sem credenciais — no-op")
        return 0
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days)).isoformat()
    date_to = today.isoformat()
    try:
        spend = await fetch_campaign_spend(date_from, date_to)
        if not spend:
            logger.info("ad_spend_sync: nenhum spend retornado (%s..%s)", date_from, date_to)
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{
            "platform": "google",
            "campaign_id": r.get("campaign_id") or None,
            "campaign_name": r.get("campaign_name"),
            "date": r.get("date"),
            "cost": r.get("cost", 0.0),
            "currency": "BRL",
            "updated_at": now_iso,
        } for r in spend if r.get("campaign_name") and r.get("date")]
        get_supabase().table("ad_spend").upsert(
            rows, on_conflict="platform,campaign_id,date"
        ).execute()
        logger.info("ad_spend_sync: upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
        return len(rows)
    except Exception as exc:
        logger.error("ad_spend_sync: falhou: %s", exc, exc_info=True)
        return 0
