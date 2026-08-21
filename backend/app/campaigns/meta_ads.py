"""Client REST (httpx) da Meta Marketing API para buscar investimento (spend) por campanha.

Env-gated + fail-soft: sem credenciais ou em erro → []. Espelha o padrão de google_ads.py.
Parsing puro (parse_spend_rows) isolado da rede para teste."""
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from app.campaigns.google_ads import AdsFetchError  # noqa: E402  (erro compartilhado entre os dois clients)


def _token() -> str:
    return os.getenv("META_ADS_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN") or ""


def _account_id() -> str:
    return os.getenv("META_AD_ACCOUNT_ID") or ""


def _act(raw: str) -> str:
    raw = (raw or "").strip()
    return raw if raw.startswith("act_") else f"act_{raw}"


def _version() -> str:
    return os.getenv("META_API_VERSION") or "v21.0"


def meta_ads_enabled() -> bool:
    return bool(_token() and _account_id())


def parse_spend_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De insights.data → [{campaign_id, campaign_name, date, cost}]. Ignora malformados."""
    out: list[dict[str, Any]] = []
    for r in data or []:
        name = r.get("campaign_name")
        if not name or "spend" not in r:
            continue
        try:
            cost = float(r.get("spend") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        out.append({
            "campaign_id": str(r.get("campaign_id") or ""),
            "campaign_name": name,
            "date": r.get("date_start"),
            "cost": cost,
        })
    return out


async def fetch_campaign_spend(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Custo por campanha/dia entre date_from e date_to (YYYY-MM-DD). Env-gated + fail-soft → []."""
    if not meta_ads_enabled():
        return []
    url = f"https://graph.facebook.com/{_version()}/{_act(_account_id())}/insights"
    params = {
        "level": "campaign",
        "fields": "campaign_id,campaign_name,spend",
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "time_increment": "1",
        "limit": "500",
        "access_token": _token(),
    }
    rows: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            next_url: str | None = url
            first = True
            for _ in range(100):  # guarda anti-loop de paginação
                resp = await client.get(next_url, params=params if first else None)
                resp.raise_for_status()
                payload = resp.json()
                rows.extend(parse_spend_rows(payload.get("data") or []))
                next_url = (payload.get("paging") or {}).get("next")
                first = False
                if not next_url:
                    break
        return rows
    except Exception as exc:
        logger.error("meta_ads: fetch_campaign_spend falhou: %s", exc)
        raise AdsFetchError(str(exc)) from exc


def parse_ad_campaign_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De insights(level=ad).data → [{ad_id, campaign_id, campaign_name}]. Ignora malformados.

    É esse mapa que liga um lead CTWA (que só carrega o `source_id` do anúncio no referral do
    webhook) à campanha que pagou por ele — a Meta não expõe campanha no payload do WhatsApp."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in data or []:
        ad_id = str(r.get("ad_id") or "")
        campaign_id = str(r.get("campaign_id") or "")
        if not ad_id or not campaign_id or ad_id in seen:
            continue
        seen.add(ad_id)
        out.append({
            "ad_id": ad_id,
            "campaign_id": campaign_id,
            "campaign_name": r.get("campaign_name") or "",
        })
    return out


async def fetch_ad_campaign_map(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Mapa anúncio→campanha dos anúncios com entrega na janela. Env-gated + fail-soft → []."""
    if not meta_ads_enabled():
        return []
    url = f"https://graph.facebook.com/{_version()}/{_act(_account_id())}/insights"
    params = {
        "level": "ad",
        "fields": "ad_id,campaign_id,campaign_name",
        "time_range": json.dumps({"since": date_from, "until": date_to}),
        "limit": "500",
        "access_token": _token(),
    }
    rows: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            next_url: str | None = url
            first = True
            for _ in range(100):
                resp = await client.get(next_url, params=params if first else None)
                resp.raise_for_status()
                payload = resp.json()
                rows.extend(parse_ad_campaign_rows(payload.get("data") or []))
                next_url = (payload.get("paging") or {}).get("next")
                first = False
                if not next_url:
                    break
        return rows
    except Exception as exc:
        # Fail-soft de propósito: sem o mapa a atribuição por campanha do Meta degrada para
        # "(não atribuído)", mas o investimento do CANAL continua correto. Não vale derrubar o sync.
        logger.error("meta_ads: fetch_ad_campaign_map falhou: %s", exc)
        return []
