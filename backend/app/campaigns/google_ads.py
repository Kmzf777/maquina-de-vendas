"""Client REST (httpx) do Google Ads para buscar investimento (spend) por campanha.

Env-gated + fail-soft: sem credenciais ou em erro de API → []. Não usa a lib gRPC google-ads
(consistente com o padrão httpx do MetaCloudClient). Parsing puro (parse_spend_rows) isolado
da rede para teste."""
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AdsFetchError(RuntimeError):
    """Falha REAL de API (404 de versão morta, token expirado, quota). Distinta de "sem gasto":
    o sync precisa dessa diferença para o botão Atualizar reportar o erro em vez de "sem dados"."""

_REQUIRED_ENV = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "GOOGLE_ADS_CUSTOMER_ID",
)
# Versão da API do Google Ads. O Google faz sunset de cada versão ~1 ano depois do lançamento
# e a versão morta responde 404 (HTML, não JSON) — o que o fail-soft daqui transformava em
# "sem investimento" silencioso. Manter atualizada; `GOOGLE_ADS_API_VERSION` permite corrigir
# em produção via env sem redeploy quando a próxima virar.
_DEFAULT_API_VERSION = "v22"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _api_version() -> str:
    return os.getenv("GOOGLE_ADS_API_VERSION") or _DEFAULT_API_VERSION


def google_ads_enabled() -> bool:
    return all(os.getenv(k) for k in _REQUIRED_ENV)


def parse_spend_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrai [{campaign_id, campaign_name, date, cost}] de uma página de resultados GAQL.

    cost = costMicros / 1_000_000. Linhas sem campaign/metrics são ignoradas."""
    out: list[dict[str, Any]] = []
    for r in results or []:
        campaign = r.get("campaign") or {}
        metrics = r.get("metrics") or {}
        segments = r.get("segments") or {}
        name = campaign.get("name")
        if not name or "costMicros" not in metrics:
            continue
        try:
            cost = int(metrics.get("costMicros") or 0) / 1_000_000
        except (TypeError, ValueError):
            cost = 0.0
        out.append({
            "campaign_id": str(campaign.get("id") or ""),
            "campaign_name": name,
            "date": segments.get("date"),
            "cost": cost,
        })
    return out


async def _get_access_token() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_TOKEN_URL, data={
                "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            return resp.json().get("access_token")
    except Exception as exc:
        logger.error("google_ads: falha ao obter access_token: %s", exc)
        return None


async def fetch_campaign_spend(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Busca custo por campanha/dia entre date_from e date_to (YYYY-MM-DD).

    Env-gated (creds ausentes → []) e fail-soft (erro → []). Retorna
    [{campaign_id, campaign_name, date, cost}]."""
    if not google_ads_enabled():
        return []
    token = await _get_access_token()
    if not token:
        return []
    customer_id = (os.getenv("GOOGLE_ADS_CUSTOMER_ID") or "").replace("-", "")
    login_cid = (os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "")
    url = f"https://googleads.googleapis.com/{_api_version()}/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or "",
        "login-customer-id": login_cid,
        "Content-Type": "application/json",
    }
    gaql = (
        "SELECT campaign.id, campaign.name, segments.date, metrics.cost_micros "
        f"FROM campaign WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'"
    )
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(50):  # guarda anti-loop de paginação
                body: dict[str, Any] = {"query": gaql}
                if page_token:
                    body["pageToken"] = page_token
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                rows.extend(parse_spend_rows(data.get("results") or []))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return rows
    except httpx.HTTPStatusError as exc:
        # 404 aqui quase sempre = versão da API descontinuada (o Google devolve HTML, não JSON).
        detail = f"HTTP {exc.response.status_code} em {_api_version()}"
        if exc.response.status_code == 404:
            detail += " — versão da API provavelmente descontinuada (ver GOOGLE_ADS_API_VERSION)"
        logger.error("google_ads: fetch_campaign_spend falhou: %s", detail)
        raise AdsFetchError(detail) from exc
    except Exception as exc:
        logger.error("google_ads: fetch_campaign_spend falhou: %s", exc)
        raise AdsFetchError(str(exc)) from exc
