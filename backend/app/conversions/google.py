# backend/app/conversions/google.py
"""Google Data Manager API (`events:ingest`) — conversões offline por clique.

Desde 15/06/2026 o UploadClickConversions da Google Ads API recusa developer tokens que não o
usavam antes; a Data Manager API é o caminho para integração nova e não exige developer token.
Um evento por request: a API não tem partial_failure — um erro rejeita o lote inteiro.
"""
import os
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.conversions.eligibility import parse_ts
from app.conversions.hashing import google_email_hash, google_phone_hash
from app.conversions.types import SendResult

INGEST_URL = "https://datamanager.googleapis.com/v1/events:ingest"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_TZ_CONTA = ZoneInfo("America/Sao_Paulo")  # fuso da conta 186-141-6291
_TIMEOUT = 20.0


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _truthy("CONVERSIONS_GOOGLE_ENABLED")


def _digits(v: str | None) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def build_event(row: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    ts = parse_ts(row["event_at"]).astimezone(_TZ_CONTA).isoformat(timespec="seconds")
    ids = []
    em = google_email_hash(lead.get("email"))
    ph = google_phone_hash(lead.get("wa_id") or lead.get("phone"))
    if em:
        ids.append({"emailAddress": em})
    if ph:
        ids.append({"phoneNumber": ph})
    ev: dict[str, Any] = {
        "adIdentifiers": {row["click_id_type"]: row["click_id"]},
        "transactionId": row["event_id"],
        "eventTimestamp": ts,
        "currency": row.get("currency") or "BRL",
    }
    if row.get("value") is not None:
        ev["conversionValue"] = float(row["value"])
    if ids:
        ev["userData"] = {"userIdentifiers": ids}
    return ev


def _action_env(stage: str) -> str:
    return f"GOOGLE_ADS_CONVERSION_ACTION_{stage.upper()}"


def build_request(row: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    customer = _digits(os.getenv("GOOGLE_ADS_CUSTOMER_ID"))
    login = _digits(os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    dest: dict[str, Any] = {
        "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": customer},
        "productDestinationId": os.getenv(_action_env(row["stage"])) or "",
    }
    if login and login != customer:
        dest["loginAccount"] = {"accountType": "GOOGLE_ADS", "accountId": login}
    return {
        "destinations": [dest],
        "encoding": "HEX",
        # Brasil não é EEE; a base legal (LGPD) está na política de privacidade.
        "consent": {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"},
        "validateOnly": _truthy("CONVERSIONS_TEST_MODE"),
        "events": [build_event(row, lead)],
    }


def _access_token(client: httpx.Client) -> str | None:
    resp = client.post(TOKEN_URL, data={
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"HTTP {resp.status_code}: {err.get('message') or resp.text[:300]}"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


def send(row: dict[str, Any], lead: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    for var in ("GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
                "GOOGLE_ADS_REFRESH_TOKEN", _action_env(row["stage"])):
        if not os.getenv(var):
            return SendResult(ok=False, permanent=True, error=f"{var} não configurado")
    body = build_request(row, lead)
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            token = _access_token(client)
            if not token:
                return SendResult(ok=False, permanent=False, error="falha ao obter access token do Google")
            resp = client.post(INGEST_URL, headers={"Authorization": f"Bearer {token}"}, json=body)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, permanent=False, error=f"rede: {exc}")
    if resp.status_code == 200:
        return SendResult(ok=True, response=resp.json())
    permanent = 400 <= resp.status_code < 500 and resp.status_code not in (401, 429)
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    return SendResult(ok=False, permanent=permanent, error=_error_message(resp), response=payload)
