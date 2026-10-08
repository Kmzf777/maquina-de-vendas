# backend/app/conversions/meta.py
"""Meta Conversions API for Business Messaging — um evento por request.

Versão padrão v25.0: existe, não expira até 2028 e não é a recém-lançada (v26.0); sobrescreva por META_CAPI_API_VERSION.

CTWA não usa pixel nem `fbc`: a Meta casa o evento pelo `ctwa_clid` + WABA. Um evento por
request de propósito: um único evento fora da janela de 7 dias derruba o lote inteiro, e o
volume (dezenas por dia) não justifica lote.

Mapa de etapas: a meta de desempenho "Maximizar o número de leads por mensagens" otimiza em
eventos de lead (`LeadSubmitted`). O nosso sinal de lead de verdade é o repasse ao vendedor
(`qualified`), não o clique: mandar `LeadSubmitted` a cada conversa iniciada faria a Meta otimizar
"conversas", que ela já conta sozinha. Por isso `lead` não tem evento aqui, e `QualifiedLead` não
é usado (não confirmado como evento de otimização em CTWA).
"""
import os
from typing import Any

import httpx

from app.conversions.eligibility import parse_ts
from app.conversions.hashing import meta_email_hash, meta_phone_hash
from app.conversions.types import SendResult

GRAPH = "https://graph.facebook.com"
EVENT_NAMES = {
    "qualified": "LeadSubmitted",
    "opportunity": "InitiateCheckout",
    "purchase": "Purchase",
}
_TIMEOUT = 15.0
# Códigos da Graph API que se resolvem sem mudar o payload (guia "Handling Errors"): token
# inválido/vencido (190, 102), permissão negada (10, 200–299) — gerar token novo resolve — e
# limites/indisponibilidade (2, 4, 17, 32, 341, 613). Ficam no backoff em vez de virar `erro`.
_TRANSIENT_CODES = {2, 4, 10, 17, 32, 102, 190, 341, 613}


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _truthy("CONVERSIONS_META_ENABLED")


_REQUIRED = ("META_CAPI_DATASET_ID", "META_CAPI_ACCESS_TOKEN", "META_WABA_ID")
_TEST_MODE_SEM_CODIGO = "modo teste ligado sem META_CAPI_TEST_EVENT_CODE"


def _test_code() -> str:
    return (os.getenv("META_CAPI_TEST_EVENT_CODE") or "").strip()


def missing_config() -> list[str]:
    """Variáveis que faltam para a Meta funcionar. Em modo teste o código de teste também é
    obrigatório: sem ele o evento sairia como real (ver `send`)."""
    falta = [v for v in _REQUIRED if not (os.getenv(v) or "").strip()]
    if _truthy("CONVERSIONS_TEST_MODE") and not _test_code():
        falta.append("META_CAPI_TEST_EVENT_CODE")
    return falta


def configured() -> bool:
    """O sender pula a plataforma (nem reivindica linhas) enquanto isto for False."""
    return not missing_config()


def build_event(row: dict[str, Any], lead: dict[str, Any], *, waba_id: str) -> dict[str, Any]:
    user_data: dict[str, Any] = {
        "whatsapp_business_account_id": waba_id,
        "ctwa_clid": row["click_id"],
    }
    ph = meta_phone_hash(lead.get("wa_id") or lead.get("phone"))
    em = meta_email_hash(lead.get("email"))
    if ph:
        user_data["ph"] = [ph]
    if em:
        user_data["em"] = [em]
    ev: dict[str, Any] = {
        "event_name": EVENT_NAMES[row["stage"]],
        "event_time": int(parse_ts(row["event_at"]).timestamp()),
        "event_id": row["event_id"],
        "action_source": "business_messaging",
        "messaging_channel": "whatsapp",
        "user_data": user_data,
    }
    if row.get("value") is not None:
        ev["custom_data"] = {"value": float(row["value"]), "currency": row.get("currency") or "BRL"}
    return ev


def build_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": [event]}
    code = _test_code()
    if _truthy("CONVERSIONS_TEST_MODE") and code:
        payload["test_event_code"] = code
    return payload


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"HTTP {resp.status_code}: {err.get('message') or resp.text[:300]}"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"


def _transient_graph_error(body: Any) -> bool:
    err = (body.get("error") if isinstance(body, dict) else None) or {}
    if not isinstance(err, dict):
        return False
    code = err.get("code")
    return bool(err.get("is_transient")) or code in _TRANSIENT_CODES \
        or (isinstance(code, int) and 200 <= code <= 299)


def send(row: dict[str, Any], lead: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    # Falta de configuração se resolve no servidor: não é permanente (entra no backoff). O sender
    # já pula a plataforma enquanto `configured()` for False; isto é a segunda trava.
    for var in _REQUIRED:
        if not (os.getenv(var) or "").strip():
            return SendResult(ok=False, permanent=False, error=f"{var} não configurado")
    # Modo teste sem código de teste mandaria um evento REAL — e o sucesso em modo teste não
    # consome a linha, então o mesmo evento real sairia de novo a cada 6 h. Não chama a Meta.
    if _truthy("CONVERSIONS_TEST_MODE") and not _test_code():
        return SendResult(ok=False, permanent=False, error=_TEST_MODE_SEM_CODIGO)
    version = os.getenv("META_CAPI_API_VERSION") or "v25.0"
    url = f"{GRAPH}/{version}/{os.getenv('META_CAPI_DATASET_ID')}/events"
    payload = build_payload(build_event(row, lead, waba_id=os.getenv("META_WABA_ID")))
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            resp = client.post(url, params={"access_token": os.getenv("META_CAPI_ACCESS_TOKEN")}, json=payload)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, permanent=False, error=f"rede: {exc}")
    if resp.status_code == 200:
        return SendResult(ok=True, response=resp.json())
    body = None
    try:
        body = resp.json()
    except ValueError:
        pass
    permanent = 400 <= resp.status_code < 500 and resp.status_code not in (401, 403, 429) \
        and not _transient_graph_error(body)
    return SendResult(ok=False, permanent=permanent, error=_error_message(resp), response=body)
