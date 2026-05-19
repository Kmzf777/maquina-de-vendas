"""
Auditoria de tráfego Meta: persiste no Supabase tudo que entra (webhooks recebidos)
e tudo que sai (requisições que o CRM envia à API da Meta).

Ambas as direções são gravadas na tabela `meta_webhook_logs` com a coluna `direction`
distinguindo 'inbound' de 'outbound'.

Logging é fire-and-forget: erros não interrompem o fluxo principal.
Chamadas síncronas ao Supabase rodam em thread pool para não bloquear o event loop.
"""

import logging
import concurrent.futures

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Thread pool dedicado ao audit — 2 workers são suficientes para inserções sequenciais
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="meta_audit"
)


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

def log_inbound(
    channel_id: str | None,
    phone_number_id: str | None,
    from_number: str | None,
    payload: dict,
    message_count: int,
) -> None:
    """Persiste webhook recebido da Meta. Fire-and-forget; nunca propaga exceções."""
    _executor.submit(_write_inbound, channel_id, phone_number_id, from_number, payload, message_count)


def _write_inbound(
    channel_id: str | None,
    phone_number_id: str | None,
    from_number: str | None,
    payload: dict,
    message_count: int,
) -> None:
    try:
        get_supabase().table("meta_webhook_logs").insert({
            "direction": "inbound",
            "channel_id": channel_id,
            "phone_number_id": phone_number_id,
            "from_number": from_number,
            "payload": payload,
            "message_count": message_count,
        }).execute()
    except Exception as exc:
        logger.warning(
            "[META AUDIT] inbound log failed channel=%s from=%s: %s",
            channel_id, from_number, exc,
        )


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

def log_outbound(
    *,
    endpoint: str,
    http_method: str,
    request_type: str,
    payload: dict,
    response: dict | None,
    status_code: int | None,
    success: bool,
    to_number: str | None = None,
    phone_number_id: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persiste requisição enviada à API da Meta. Fire-and-forget; nunca propaga exceções."""
    _executor.submit(
        _write_outbound,
        endpoint, http_method, request_type, payload, response,
        status_code, success, to_number, phone_number_id, error_message,
    )


def _write_outbound(
    endpoint: str,
    http_method: str,
    request_type: str,
    payload: dict,
    response: dict | None,
    status_code: int | None,
    success: bool,
    to_number: str | None,
    phone_number_id: str | None,
    error_message: str | None,
) -> None:
    try:
        get_supabase().table("meta_webhook_logs").insert({
            "direction": "outbound",
            "endpoint": endpoint,
            "http_method": http_method,
            "request_type": request_type,
            "payload": payload,
            "response": response,
            "status_code": status_code,
            "success": success,
            "to_number": to_number,
            "phone_number_id": phone_number_id,
            "error_message": error_message,
        }).execute()
    except Exception as exc:
        logger.warning(
            "[META AUDIT] outbound log failed type=%s to=%s status=%s: %s",
            request_type, to_number, status_code, exc,
        )
