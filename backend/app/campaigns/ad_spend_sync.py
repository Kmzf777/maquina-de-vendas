"""Sync diário do investimento do Google Ads e Meta Ads para a tabela ad_spend (upsert idempotente).

Env-gated (no-op sem credenciais) e fail-soft. Rodado pelo tick diário do worker
(app/worker/main.py::_ad_spend_sync_tick) e sob demanda pelo botão Atualizar do /trafego;
o script scripts/sync_google_ads_spend.py continua disponível para rodar manualmente.

Fail-soft com RECIBO: um erro de API não derruba o worker, mas volta em `errors` para o botão
Atualizar. Sem isso, a versão v21 do Google Ads morreu em 11/08/2026 e o sync ficou dez dias
respondendo "0 linhas" como se fosse dia sem gasto — foi o que escondeu o bug."""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.campaigns.google_ads import fetch_campaign_spend, google_ads_enabled, AdsFetchError
from app.campaigns.meta_ads import (
    fetch_campaign_spend as meta_fetch_campaign_spend,
    fetch_ad_campaign_map,
    meta_ads_enabled,
)

logger = logging.getLogger(__name__)


def _window(days: int) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def _spend_rows(spend: list[dict], platform: str) -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    return [{
        "platform": platform,
        "campaign_id": r.get("campaign_id") or None,
        "campaign_name": r.get("campaign_name"),
        "date": r.get("date"),
        "cost": r.get("cost", 0.0),
        "currency": "BRL",
        "updated_at": now_iso,
    } for r in spend if r.get("campaign_name") and r.get("date")]


async def sync_google_ads_spend(days: int = 30) -> int:
    """Busca o spend dos últimos `days` dias e faz upsert em ad_spend. Retorna nº de linhas."""
    return (await _sync_google(days))[0]


async def _sync_google(days: int) -> tuple[int, str | None]:
    if not google_ads_enabled():
        logger.info("ad_spend_sync: Google Ads sem credenciais — no-op")
        return 0, None
    date_from, date_to = _window(days)
    try:
        spend = await fetch_campaign_spend(date_from, date_to)
    except AdsFetchError as exc:
        logger.error("ad_spend_sync: Google Ads falhou: %s", exc)
        return 0, str(exc)
    if not spend:
        logger.info("ad_spend_sync: nenhum spend retornado (%s..%s)", date_from, date_to)
        return 0, None
    try:
        rows = _spend_rows(spend, "google")
        get_supabase().table("ad_spend").upsert(rows, on_conflict="platform,campaign_id,date").execute()
        logger.info("ad_spend_sync: upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
        return len(rows), None
    except Exception as exc:
        logger.error("ad_spend_sync: falhou: %s", exc, exc_info=True)
        return 0, str(exc)


async def sync_meta_ads_spend(days: int = 30) -> int:
    """Busca o spend do Meta Ads e faz upsert em ad_spend (platform='meta'). Retorna nº de linhas."""
    return (await _sync_meta(days))[0]


async def _sync_meta(days: int) -> tuple[int, str | None]:
    if not meta_ads_enabled():
        logger.info("ad_spend_sync: Meta Ads sem credenciais — no-op")
        return 0, None
    date_from, date_to = _window(days)
    try:
        spend = await meta_fetch_campaign_spend(date_from, date_to)
    except AdsFetchError as exc:
        logger.error("ad_spend_sync(meta): falhou: %s", exc)
        return 0, str(exc)
    if not spend:
        logger.info("ad_spend_sync(meta): nenhum spend retornado (%s..%s)", date_from, date_to)
        return 0, None
    try:
        rows = _spend_rows(spend, "meta")
        get_supabase().table("ad_spend").upsert(rows, on_conflict="platform,campaign_id,date").execute()
        logger.info("ad_spend_sync(meta): upsert de %d linhas (%s..%s)", len(rows), date_from, date_to)
    except Exception as exc:
        logger.error("ad_spend_sync(meta): falhou: %s", exc, exc_info=True)
        return 0, str(exc)
    await _sync_meta_ad_map(date_from, date_to)
    return len(rows), None


async def _sync_meta_ad_map(date_from: str, date_to: str) -> int:
    """Upsert do mapa anúncio→campanha (meta_ad_campaigns). Fail-soft: erro aqui só degrada a
    atribuição por campanha do Meta; o investimento do canal não depende dele."""
    try:
        mapping = await fetch_ad_campaign_map(date_from, date_to)
        if not mapping:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{
            "ad_id": m["ad_id"],
            "campaign_id": m["campaign_id"],
            "campaign_name": m.get("campaign_name") or "",
            "updated_at": now_iso,
        } for m in mapping]
        get_supabase().table("meta_ad_campaigns").upsert(rows, on_conflict="ad_id").execute()
        logger.info("ad_spend_sync(meta): mapa anúncio→campanha com %d entradas", len(rows))
        return len(rows)
    except Exception as exc:
        logger.error("ad_spend_sync(meta): mapa anúncio→campanha falhou: %s", exc)
        return 0


async def sync_all_ad_spend(days: int = 30) -> dict[str, object]:
    """Sincroniza Google + Meta (cada um env-gated/fail-soft).

    Retorna {'google': n, 'meta': m, 'errors': {plataforma: motivo}} — `errors` vazio significa
    que as APIs responderam; 0 linhas com `errors` vazio é dia sem gasto de verdade."""
    g, g_err = await _sync_google(days)
    m, m_err = await _sync_meta(days)
    errors: dict[str, str] = {}
    if g_err:
        errors["google"] = g_err
    if m_err:
        errors["meta"] = m_err
    return {"google": g, "meta": m, "errors": errors}
