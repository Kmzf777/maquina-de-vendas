"""Conversões outbound (Vendas Offline) — Meta CAPI e Google Offline Conversions.

Fundação para devolver o evento de COMPRA às plataformas de anúncio quando uma venda é
confirmada no CRM, comprovando ROI:

  * Meta Conversions API (CAPI): usa `ctwa_clid` (Click-to-WhatsApp) OU `fbclid` (tráfego
    de site) + dados do usuário com hash SHA-256 (e-mail e telefone).
  * Google Offline Conversions (Vendas Offline): usa `gclid`.

Princípios:
  - **Defensivo / fail-soft:** nenhuma falha de disparo pode quebrar o fluxo de venda.
  - **Env-gated:** credenciais vêm 100% de variáveis de ambiente. Sem credenciais, o
    disparo é um no-op logado (útil em dev/homolog e enquanto a integração não é ativada).
  - **Funções puras testáveis:** o hashing e a montagem do payload não fazem I/O — o envio
    HTTP (httpx) é isolado e só roda quando há credenciais.

Variáveis de ambiente (todas opcionais — ausência desativa o respectivo canal):
  META_CAPI_PIXEL_ID, META_CAPI_ACCESS_TOKEN, META_CAPI_API_VERSION (default v21.0),
  META_CAPI_TEST_EVENT_CODE (opcional, para o Test Events do Gerenciador),
  GOOGLE_ADS_CUSTOMER_ID, GOOGLE_ADS_CONVERSION_ACTION_ID, GOOGLE_ADS_DEVELOPER_TOKEN.
"""
import hashlib
import logging
import os
import re
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com"
_DEFAULT_API_VERSION = "v21.0"
_HTTP_TIMEOUT = 10.0

_DIGITS_RE = re.compile(r"\D+")

# Mapa canônico → nome de evento na Meta. Override por env META_EVENT_NAME_<EVENTO>.
_DEFAULT_META_EVENT_NAMES = {
    "lead": "Lead",
    "qualified": "Lead",
    "opportunity": "Oportunidade_Criada",
    "purchase": "Purchase",
}


def meta_event_name(event: str) -> str:
    """Nome do evento na Meta para um evento canônico do funil (env-overridable)."""
    default = _DEFAULT_META_EVENT_NAMES.get(event, event)
    return os.environ.get(f"META_EVENT_NAME_{event.upper()}", default)


# --------------------------------------------------------------------------- #
# Hashing & normalização (funções puras)
# --------------------------------------------------------------------------- #

def _sha256(value: str) -> str:
    """SHA-256 hex de uma string já normalizada (lowercase/trim feito pelo chamador)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email(email: str | None) -> str | None:
    """Normaliza (trim + lowercase) e aplica SHA-256. None/vazio → None."""
    if not email:
        return None
    norm = email.strip().lower()
    return _sha256(norm) if norm else None


def hash_phone(phone: str | None) -> str | None:
    """Normaliza para E.164 só-dígitos (sem '+') e aplica SHA-256. None/vazio → None.

    A Meta exige o telefone só com dígitos incluindo código do país antes do hash.
    """
    if not phone:
        return None
    digits = _DIGITS_RE.sub("", phone)
    return _sha256(digits) if digits else None


def build_fbc(fbclid: str | None, event_time: int | None = None) -> str | None:
    """Monta o cookie `fbc` a partir de um fbclid cru: fb.1.<timestamp_ms>.<fbclid>.

    É o formato que a Meta CAPI espera quando só temos o fbclid (tráfego de site), não o
    cookie _fbc original. None/vazio → None.
    """
    if not fbclid:
        return None
    ts_ms = int((event_time or time.time()) * 1000)
    return f"fb.1.{ts_ms}.{fbclid}"


# --------------------------------------------------------------------------- #
# Montagem de payloads (funções puras)
# --------------------------------------------------------------------------- #

def build_meta_capi_event(
    lead: dict[str, Any],
    value: float | None = None,
    currency: str = "BRL",
    event_name: str = "Purchase",
    event_time: int | None = None,
) -> dict[str, Any]:
    """Monta UM evento de conversão da Meta CAPI a partir do lead.

    - user_data: e-mail e telefone com hash SHA-256 (quando disponíveis).
    - Atribuição: prioriza `ctwa_clid` (Click-to-WhatsApp → action_source=business_messaging);
      se ausente, usa `fbclid` convertido em `fbc` (tráfego de site → action_source=website).
    """
    event_time = event_time or int(time.time())

    user_data: dict[str, Any] = {}
    em = hash_email(lead.get("email"))
    ph = hash_phone(lead.get("wa_id") or lead.get("phone"))
    if em:
        user_data["em"] = [em]
    if ph:
        user_data["ph"] = [ph]

    ctwa_clid = lead.get("ctwa_clid")
    fbclid = lead.get("fbclid")
    if ctwa_clid:
        # CTWA: a Meta correlaciona pelo ctwa_clid + canal de mensageria.
        action_source = "business_messaging"
        user_data["ctwa_clid"] = ctwa_clid
        messaging_channel: str | None = "whatsapp"
    else:
        action_source = "website"
        messaging_channel = None
        fbc = build_fbc(fbclid, event_time)
        if fbc:
            user_data["fbc"] = fbc

    event: dict[str, Any] = {
        "event_name": event_name,
        "event_time": event_time,
        "action_source": action_source,
        "user_data": user_data,
    }
    if messaging_channel:
        event["messaging_channel"] = messaging_channel

    if value is not None:
        event["custom_data"] = {"value": float(value), "currency": currency}

    return event


def build_meta_capi_payload(
    lead: dict[str, Any],
    value: float | None = None,
    currency: str = "BRL",
    event_name: str = "Purchase",
    event_time: int | None = None,
) -> dict[str, Any]:
    """Envelope final da Meta CAPI: {"data": [evento], "test_event_code"?: ...}."""
    payload: dict[str, Any] = {
        "data": [build_meta_capi_event(lead, value, currency, event_name, event_time)],
    }
    test_code = os.environ.get("META_CAPI_TEST_EVENT_CODE")
    if test_code:
        payload["test_event_code"] = test_code
    return payload


def build_google_offline_conversion(
    lead: dict[str, Any],
    value: float | None = None,
    currency: str = "BRL",
    conversion_time: str | None = None,
) -> dict[str, Any] | None:
    """Monta a conversão offline do Google (Vendas Offline) a partir do gclid.

    Sem gclid não há como atribuir no Google → retorna None. O envio real exige a Google
    Ads API (OAuth + client lib); aqui montamos o corpo canônico do ClickConversion para
    ser enviado quando as credenciais/SDK estiverem disponíveis.
    """
    gclid = lead.get("gclid")
    if not gclid:
        return None
    conv: dict[str, Any] = {
        "gclid": gclid,
        "conversion_action": os.environ.get("GOOGLE_ADS_CONVERSION_ACTION_ID", ""),
        "conversion_date_time": conversion_time or "",
    }
    if value is not None:
        conv["conversion_value"] = float(value)
        conv["currency_code"] = currency
    return conv


# --------------------------------------------------------------------------- #
# Disparo HTTP (env-gated, fail-soft)
# --------------------------------------------------------------------------- #

def _meta_credentials() -> tuple[str, str, str] | None:
    pixel_id = os.environ.get("META_CAPI_PIXEL_ID")
    access_token = os.environ.get("META_CAPI_ACCESS_TOKEN")
    if not pixel_id or not access_token:
        return None
    api_version = os.environ.get("META_CAPI_API_VERSION", _DEFAULT_API_VERSION)
    return pixel_id, access_token, api_version


def _send_meta_capi(
    lead: dict[str, Any],
    value: float | None,
    currency: str,
    event_name: str = "Purchase",
) -> dict[str, Any]:
    """Envia o evento para a Meta CAPI se houver credenciais. Fail-soft."""
    creds = _meta_credentials()
    if not creds:
        logger.info("[CAPI] Meta sem credenciais (META_CAPI_PIXEL_ID/ACCESS_TOKEN) — disparo ignorado")
        return {"sent": False, "reason": "no_credentials"}

    if not (lead.get("ctwa_clid") or lead.get("fbclid")):
        logger.info("[CAPI] Lead %s sem ctwa_clid nem fbclid — nada a atribuir na Meta", lead.get("id"))
        return {"sent": False, "reason": "no_click_id"}

    pixel_id, access_token, api_version = creds
    url = f"{META_API_BASE}/{api_version}/{pixel_id}/events"
    payload = build_meta_capi_payload(lead, value, currency, event_name=event_name)
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(url, params={"access_token": access_token}, json=payload)
            resp.raise_for_status()
        logger.info("[CAPI] Meta %s enviado para lead %s (HTTP %s)", event_name, lead.get("id"), resp.status_code)
        return {"sent": True, "status_code": resp.status_code}
    except Exception as exc:
        logger.error("[CAPI] Falha ao enviar evento Meta para lead %s: %s", lead.get("id"), exc, exc_info=True)
        return {"sent": False, "reason": "http_error", "error": str(exc)}


def _send_google_conversion(lead: dict[str, Any], value: float | None, currency: str) -> dict[str, Any]:
    """Prepara/dispara a conversão offline do Google. Fail-soft.

    O envio real depende da Google Ads API (OAuth2 + google-ads SDK), ainda não adicionada
    ao projeto. Enquanto isso, montamos o payload e logamos — ponto único para plugar o SDK.
    """
    conv = build_google_offline_conversion(lead, value, currency)
    if conv is None:
        return {"sent": False, "reason": "no_gclid"}
    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not customer_id or not dev_token:
        logger.info("[CAPI] Google sem credenciais (GOOGLE_ADS_*) — conversão montada mas não enviada")
        return {"sent": False, "reason": "no_credentials", "payload": conv}
    # TODO(integração): enviar `conv` via google-ads SDK (UploadClickConversionsRequest).
    logger.info("[CAPI] Google Offline Conversion preparada para lead %s (envio via SDK pendente)", lead.get("id"))
    return {"sent": False, "reason": "sdk_pending", "payload": conv}


def dispatch_conversion(
    lead: dict[str, Any],
    event: str,
    value: float | None = None,
    currency: str = "BRL",
) -> dict[str, Any]:
    """Dispara UM evento de conversão canônico (lead|qualified|opportunity|purchase) p/ Meta+Google.

    Fail-soft de ponta a ponta. Retorna {"meta": {...}, "google": {...}}.
    """
    if not lead:
        return {"meta": {"sent": False, "reason": "no_lead"}, "google": {"sent": False, "reason": "no_lead"}}
    meta_result = _send_meta_capi(lead, value, currency, event_name=meta_event_name(event))
    google_result = _send_google_conversion(lead, value, currency)
    return {"meta": meta_result, "google": google_result}


def dispatch_purchase_conversion(
    lead: dict[str, Any],
    value: float | None = None,
    currency: str = "BRL",
) -> dict[str, Any]:
    """Compat: dispara a conversão de COMPRA (event='purchase').

    Orquestra o disparo da conversão de COMPRA para Meta e Google a partir de um lead.
    Fail-soft de ponta a ponta: cada canal é independente e nunca levanta. Retorna um
    resumo {"meta": {...}, "google": {...}} para logging/observabilidade.
    """
    return dispatch_conversion(lead, "purchase", value, currency)


def dispatch_purchase_conversion_background(
    lead: dict[str, Any],
    value: float | None = None,
    currency: str = "BRL",
) -> None:
    """Versão não-bloqueante: roda o disparo numa daemon thread e retorna na hora.

    Para chamadores SÍNCRONOS sem acesso a FastAPI BackgroundTasks (ex.: o worker de
    automação). A latência da Meta/Google nunca bloqueia a thread principal. Fail-soft: a
    thread captura qualquer exceção. Em contexto de request HTTP, prefira passar
    `dispatch_purchase_conversion` direto para BackgroundTasks.add_task.
    """
    def _run() -> None:
        try:
            dispatch_purchase_conversion(lead, value, currency)
        except Exception as exc:  # pragma: no cover - defensivo
            logger.error("[CAPI] erro no disparo em background para lead %s: %s", lead.get("id"), exc, exc_info=True)

    threading.Thread(target=_run, name="capi-dispatch", daemon=True).start()
