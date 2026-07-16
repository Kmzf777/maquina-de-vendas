import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import redis

from app.config import settings
from app.db.supabase import get_supabase, run_with_retry

logger = logging.getLogger(__name__)

# Marcador Redis de "pausado POR BILLING" (wartime T4). Distingue o pause automático
# de billing do pause manual do operador SEM migração de schema — só broadcasts com
# marcador são elegíveis ao auto-resume quando o billing normaliza. TTL de 7 dias:
# billing parado além disso é incidente de outra ordem, resume manual.
_BILLING_PAUSE_KEY_PREFIX = "billing:paused_broadcast:"
_BILLING_PAUSE_TTL_SECONDS = 7 * 24 * 3600


def _get_redis() -> redis.Redis:
    """Cliente Redis síncrono de curta duração (padrão de app/events/bus.py).

    Este módulo é chamado tanto de contexto sync (webhook thread) quanto async; o
    cliente síncrono com timeouts curtos é aceitável porque todo uso aqui é
    best-effort e envolto em try/except (Redis fora nunca derruba o caller).
    """
    return redis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=2, socket_timeout=2,
    )


def get_broadcast(broadcast_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute()
    return result.data


def get_pending_broadcast_leads(broadcast_id: str, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("*, leads!inner(id, phone, wa_id, wa_id_confirmed_at, last_customer_message_at, bsuid, stage, name, metadata)")
        .eq("broadcast_id", broadcast_id)
        .eq("status", "pending")
        .limit(limit)
        .execute()
    )
    return result.data


def pause_broadcast_for_billing(broadcast_id: str) -> bool:
    """Pausa um broadcast por falha de billing (131042). Idempotente e não-destrutivo.

    Filtra por status ativo (running/scheduled) para nunca reverter um broadcast já
    completed/failed/paused. Retorna True se alguma linha foi efetivamente pausada.

    Chamado pelo webhook de delivery-status (meta_router) porque a Meta ACEITA o send
    do template com HTTP 200 e só reporta o débito depois, de forma assíncrona — o
    pause síncrono no worker nunca dispara para esse caso.
    """
    sb = get_supabase()
    result = (
        sb.table("broadcasts")
        .update({"status": "paused"})
        .eq("id", broadcast_id)
        .in_("status", ["running", "scheduled"])
        .execute()
    )
    paused = bool(result.data)
    if paused:
        logger.critical(
            "[BROADCAST][BILLING] broadcast %s PAUSADO automaticamente — erro 131042",
            broadcast_id,
        )
        # Marcador best-effort p/ o auto-resume (wartime T4): Redis fora neste momento
        # → marcador perdido → resume manual (status quo de antes, sem regressão).
        try:
            _get_redis().set(
                f"{_BILLING_PAUSE_KEY_PREFIX}{broadcast_id}", "1",
                ex=_BILLING_PAUSE_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "[BROADCAST][BILLING] marcador Redis do pause não gravado p/ %s: %s "
                "(auto-resume indisponível; retome manualmente)",
                broadcast_id, exc,
            )
    return paused


def resume_broadcasts_after_billing() -> int:
    """Auto-resume dos broadcasts pausados POR BILLING quando o billing normaliza.

    Chamado pelo health check horário (follow_up/scheduler) no ramo que auto-resolve
    os alertas de billing. Varre os marcadores `billing:paused_broadcast:*` (SCAN):
      - status ainda 'paused'  → volta a 'running' + wake-up do worker + alerta
        warning `broadcast_auto_resumed` (o operador SABE que voltou sozinho);
      - status != 'paused' (operador mexeu: retomou/cancelou) → só remove o marcador —
        a decisão humana vence, nunca ressuscitamos um broadcast mexido na mão.

    Fail-soft total: qualquer erro (Redis/banco) loga e segue — o health check que
    nos chama jamais pode quebrar por causa do resume. Retorna o nº de broadcasts
    efetivamente retomados.
    """
    try:
        client = _get_redis()
        keys = list(client.scan_iter(match=f"{_BILLING_PAUSE_KEY_PREFIX}*", count=100))
    except Exception as exc:
        logger.warning("[BROADCAST][BILLING] resume: varredura Redis falhou: %s", exc)
        return 0

    resumed = 0
    for key in keys:
        broadcast_id = str(key).rsplit(":", 1)[-1]
        if not broadcast_id:
            continue
        try:
            # UPDATE guardado por status='paused': linha afetada = era pause de billing
            # ainda vigente; nenhuma linha = o operador já mexeu (ou o id sumiu).
            result = (
                get_supabase()
                .table("broadcasts")
                .update({"status": "running"})
                .eq("id", broadcast_id)
                .eq("status", "paused")
                .execute()
            )
        except Exception as exc:
            # Banco falhou p/ ESTE id: mantém o marcador (o próximo health check retenta).
            logger.warning(
                "[BROADCAST][BILLING] resume: update falhou p/ %s: %s", broadcast_id, exc
            )
            continue

        if result.data:
            resumed += 1
            logger.warning(
                "[BROADCAST][BILLING] broadcast %s RETOMADO automaticamente — billing normalizado",
                broadcast_id,
            )
            try:
                # Import tardio: events.bus é leve, mas mantém o padrão do módulo
                # (nenhuma dependência nova em import-time de service).
                from app.events.bus import emit_event
                emit_event("broadcasts")  # wake-up do worker (fail-open)
            except Exception as exc:
                logger.warning("[BROADCAST][BILLING] resume: emit_event falhou: %s", exc)
            try:
                from app.alerts.service import create_system_alert
                create_system_alert(
                    "broadcast_auto_resumed",
                    "Disparo retomado automaticamente — billing normalizado",
                    (
                        f"O broadcast {broadcast_id} estava pausado por falha de billing "
                        f"(erro Meta 131042) e foi retomado automaticamente após o health "
                        f"check confirmar que o billing normalizou. Nenhuma ação necessária; "
                        f"acompanhe o andamento no painel de disparos."
                    ),
                    severity="warning",
                    metadata={"broadcast_id": broadcast_id},
                )
            except Exception as exc:
                logger.warning("[BROADCAST][BILLING] resume: alerta não criado: %s", exc)

        try:
            client.delete(key)
        except Exception as exc:
            logger.warning("[BROADCAST][BILLING] resume: DEL do marcador %s falhou: %s", key, exc)

    return resumed


# Os marks/increments abaixo são hot writes de rajada de disparo: um GOAWAY (HTTP/2)
# no meio do request perdia o estado do lead silenciosamente (broadcast_lead preso em
# 'processing' até a crash-recovery, contadores furados). run_with_retry (T6) repete
# SOMENTE httpx.TransportError — erros de aplicação (4xx/5xx) nunca são mascarados.

def mark_broadcast_lead_sent(bl_id: str) -> None:
    run_with_retry(
        lambda: get_supabase().table("broadcast_leads").update({
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bl_id).execute(),
        label="broadcast.mark_lead_sent",
    )


def mark_broadcast_lead_failed(bl_id: str, error: str) -> None:
    run_with_retry(
        lambda: get_supabase().table("broadcast_leads").update({
            "status": "failed",
            "error_message": error,
        }).eq("id", bl_id).execute(),
        label="broadcast.mark_lead_failed",
    )


def requeue_broadcast_lead(bl_id: str) -> None:
    """Devolve um lead reivindicado ('processing') para 'pending' após uma falha
    TRANSITÓRIA de conexão (GOAWAY/RemoteProtocolError/ConnectError) que escapou dos
    retries HTTP do _request_with_retry — em vez de queimá-lo como falha permanente.

    Guardado por status='processing' (idempotente): nunca reverte um lead já sent/failed
    nem toca um pending. O próximo tick (ou a crash-recovery de 'processing' órfão)
    retenta o envio. Não incrementa o contador de falhas — não foi uma falha real."""
    run_with_retry(
        lambda: get_supabase().table("broadcast_leads").update({
            "status": "pending",
            "claimed_at": None,
        }).eq("id", bl_id).eq("status", "processing").execute(),
        label="broadcast.requeue_lead",
    )


def increment_broadcast_sent(broadcast_id: str) -> None:
    run_with_retry(
        lambda: get_supabase().rpc(
            "increment_broadcast_sent", {"broadcast_id_param": broadcast_id}
        ).execute(),
        label="broadcast.increment_sent",
    )


def increment_broadcast_failed(broadcast_id: str) -> None:
    run_with_retry(
        lambda: get_supabase().rpc(
            "increment_broadcast_failed", {"broadcast_id_param": broadcast_id}
        ).execute(),
        label="broadcast.increment_failed",
    )


def save_broadcast_lead_wamid(bl_id: str, wamid: str) -> None:
    run_with_retry(
        lambda: get_supabase().table("broadcast_leads").update(
            {"wamid": wamid}
        ).eq("id", bl_id).execute(),
        label="broadcast.save_lead_wamid",
    )


def find_broadcast_lead_by_wamid(wamid: str) -> dict | None:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("id, broadcast_id, delivered_at")
        .eq("wamid", wamid)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_broadcast_lead_delivered(bl_id: str) -> bool:
    """Atomically mark bl as delivered only if not already marked.

    Returns True if the row was updated (first delivery), False if already
    delivered (duplicate webhook). Caller must only increment the counter
    when this returns True.
    """
    result = run_with_retry(
        lambda: get_supabase().table("broadcast_leads").update({
            "status": "delivered",
            "delivered_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bl_id).is_("delivered_at", "null").execute(),
        label="broadcast.mark_lead_delivered",
    )
    return bool(result.data)


def increment_broadcast_delivered(broadcast_id: str) -> None:
    run_with_retry(
        lambda: get_supabase().rpc(
            "increment_broadcast_delivered", {"broadcast_id_param": broadcast_id}
        ).execute(),
        label="broadcast.increment_delivered",
    )


def record_broadcast_reply(lead_id: str) -> None:
    """Marks the most recent active broadcast_lead for this lead as replied (48h window).

    Idempotent: if first_replied_at is already set, the query returns no rows
    and no update is made.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    result = (
        sb.table("broadcast_leads")
        .select("id")
        .eq("lead_id", lead_id)
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", cutoff)
        .order("sent_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        bl_id = result.data[0]["id"]
        sb.table("broadcast_leads").update({
            "first_replied_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bl_id).execute()
        logger.info(
            "[BROADCAST] Resposta registrada: lead=%s broadcast_lead=%s",
            lead_id, bl_id,
        )
    else:
        logger.debug(
            "[BROADCAST] Nenhum broadcast_lead ativo encontrado para resposta do lead=%s",
            lead_id,
        )
