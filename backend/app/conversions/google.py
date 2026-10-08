# backend/app/conversions/google.py
"""Google Data Manager API (`events:ingest`) — conversões offline por clique.

Desde 15/06/2026 o UploadClickConversions da Google Ads API recusa developer tokens que não o
usavam antes; a Data Manager API é o caminho para integração nova e não exige developer token.
Um evento por request: a API não tem partial_failure — um erro rejeita o lote inteiro.
"""
import hashlib
import os
import threading
import time
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
# O access token do OAuth vale ~1 h: guarda por 50 min (margem) em vez de um refresh por envio.
_TOKEN_TTL = 50 * 60
_token_lock = threading.Lock()
_token_cache: dict[str, Any] = {}
_monotonic = time.monotonic  # trocável nos testes


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _truthy("CONVERSIONS_GOOGLE_ENABLED")


# Credenciais da conta (valem para todas as linhas). O ID da ação é por etapa e é checado linha
# a linha no `send`.
_REQUIRED = ("GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
             "GOOGLE_ADS_REFRESH_TOKEN")


def missing_config() -> list[str]:
    return [v for v in _REQUIRED if not _env(v)]


def configured() -> bool:
    """O sender pula a plataforma (nem reivindica linhas) enquanto isto for False."""
    return not missing_config()


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


def action_configured(stage: str) -> bool:
    """A etapa tem o ID da ação configurado? O sender nem reivindica as linhas das etapas sem
    ele (ficam `pendente`, sem gastar tentativa)."""
    return bool(_env(_action_env(stage)))


def build_request(row: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    customer = _digits(os.getenv("GOOGLE_ADS_CUSTOMER_ID"))
    login = _digits(os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    dest: dict[str, Any] = {
        "operatingAccount": {"accountType": "GOOGLE_ADS", "accountId": customer},
        "productDestinationId": _env(_action_env(row["stage"])),
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


def _reset_token_cache() -> None:
    with _token_lock:
        _token_cache.clear()


def _cred_key(creds: dict[str, str]) -> str:
    # Chave = hash das credenciais: trocar o refresh token no .env não reaproveita o token velho.
    raw = "\0".join(creds[k] for k in ("client_id", "client_secret", "refresh_token"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _access_token(client: httpx.Client) -> tuple[str | None, str | None, bool]:
    """(token, erro, erro_de_credencial). Token em cache por processo (ver `_TOKEN_TTL`)."""
    creds = {"client_id": _env("GOOGLE_ADS_CLIENT_ID"), "client_secret": _env("GOOGLE_ADS_CLIENT_SECRET"),
             "refresh_token": _env("GOOGLE_ADS_REFRESH_TOKEN")}
    key = _cred_key(creds)
    with _token_lock:
        if _token_cache.get("key") == key and _token_cache.get("exp", 0) > _monotonic():
            return _token_cache["token"], None, False
    resp = client.post(TOKEN_URL, data={**creds, "grant_type": "refresh_token"})
    if resp.status_code != 200:
        try:
            codigo = (resp.json() or {}).get("error")
        except ValueError:
            codigo = None
        detalhe = f"HTTP {resp.status_code}" + (f" {codigo}" if codigo else "")
        # 400/401 do OAuth = credencial ruim (invalid_grant: refresh token revogado/expirado;
        # invalid_client). 5xx/429 é o OAuth fora do ar — não é credencial.
        auth = resp.status_code in (400, 401, 403)
        return None, f"falha ao obter access token do Google ({detalhe})", auth
    try:
        token = resp.json().get("access_token")
    except ValueError:
        token = None
    if not token:
        return None, "falha ao obter access token do Google (resposta sem access_token)", False
    with _token_lock:
        _token_cache.update(key=key, token=token, exp=_monotonic() + _TOKEN_TTL)
    return token, None, False


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"HTTP {resp.status_code}: {err.get('message') or resp.text[:300]}"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


def send(row: dict[str, Any], lead: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    # Falta de configuração (inclusive o ID da ação desta etapa) se resolve no servidor: não é
    # permanente, entra no backoff em vez de virar `erro` de vez.
    for var in (*_REQUIRED, _action_env(row["stage"])):
        if not _env(var):
            return SendResult(ok=False, permanent=False, error=f"{var} não configurado")
    body = build_request(row, lead)
    # Erro de rede é sempre transitório aqui, inclusive resposta perdida depois de o request
    # sair: o Google deduplica pelo `transactionId` (= event_id), então reenviar é seguro.
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            token, erro, auth = _access_token(client)
            if not token:
                return SendResult(ok=False, permanent=False, error=erro, auth_error=auth)
            resp = client.post(INGEST_URL, headers={"Authorization": f"Bearer {token}"}, json=body)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, permanent=False, error=f"rede: {exc}")
    if resp.status_code == 200:
        # Aceito. Corpo que não é JSON não pode virar falha.
        try:
            ok_body = resp.json()
        except ValueError:
            ok_body = {"raw": resp.text[:500]}
        return SendResult(ok=True, response=ok_body if isinstance(ok_body, dict) else {"raw": ok_body})
    if resp.status_code == 401:
        _reset_token_cache()  # token em cache revogado: o próximo envio pede outro
    # 401/403 (credencial revogada, sem acesso à conta) se resolvem gerando token novo: a fila
    # espera no backoff em vez de virar `erro` de vez — e o sender para o Google no tick.
    permanent = 400 <= resp.status_code < 500 and resp.status_code not in (401, 403, 429)
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    return SendResult(ok=False, permanent=permanent, error=_error_message(resp), response=payload,
                      auth_error=resp.status_code in (401, 403))
