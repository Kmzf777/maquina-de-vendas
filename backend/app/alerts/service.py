import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_BILLING_ERROR_CODE = 131042


def create_system_alert(
    type: str,
    title: str,
    message: str,
    severity: str = "error",
    metadata: dict | None = None,
) -> None:
    try:
        sb = get_supabase()
        sb.table("system_alerts").insert({
            "type": type,
            "severity": severity,
            "title": title,
            "message": message,
            "metadata": metadata or {},
        }).execute()
    except Exception as exc:
        logger.error("[ALERT] Failed to persist system alert type=%s: %s", type, exc)
    # Despacho externo SEMPRE roda — mesmo com o insert falhado. Alerta que só vive no
    # CRM não reduz MTTR (o operador descobre incidente por reclamação de lead); e se o
    # banco está fora, avisar fora do banco é ainda MAIS importante. Fail-soft absoluto.
    _notify_external(type, title, message, severity)


def _notify_external(type: str, title: str, message: str, severity: str) -> None:
    """Despacha o alerta para fora do CRM (wartime T2, 10/07).

    Roteamento por severidade:
      - critical → Sentry (level=error; e-mail do free tier é o canal garantido)
                   + WhatsApp ao admin (ADMIN_ALERT_PHONE) — best-effort.
      - warning  → só Sentry (level=warning).
      - demais   → nada (info/error legado continuam sendo só banner do CRM).

    Fail-soft ABSOLUTO: esta função roda no caminho de alerta de incidente — se ela
    levantar, piora o próprio incidente que está reportando. Nenhuma exceção escapa.
    """
    try:
        if severity not in ("critical", "warning"):
            return
        _notify_sentry(type, title, message, severity)
        if severity == "critical":
            _notify_whatsapp_admin(title, message)
    except Exception as exc:
        logger.warning("[ALERT] despacho externo falhou (seguindo sem): %s", exc)


def _notify_sentry(type: str, title: str, message: str, severity: str) -> None:
    """capture_message no Sentry — mesmo padrão fail-open de app/observability.py.

    Sem o pacote instalado o import levanta (engolido); sem DSN inicializado o
    capture_message do SDK já é no-op por conta própria. Zero efeito em dev local.
    """
    try:
        import sentry_sdk

        level = "error" if severity == "critical" else "warning"
        sentry_sdk.capture_message(f"[ALERT][{type}] {title}: {message}", level=level)
    except Exception as exc:
        logger.debug("[ALERT] Sentry indisponível para despacho (fail-open): %s", exc)


async def _send_admin_text(provider, phone: str, body: str) -> None:
    """Envio awaitable com try próprio — a task agendada nunca morre com exceção solta."""
    try:
        await provider.send_text(phone, body)
        logger.info("[ALERT] alerta critical enviado ao WhatsApp do admin (%s...)", phone[:6])
    except Exception as exc:
        logger.warning("[ALERT] envio WhatsApp ao admin falhou (best-effort): %s", exc)


def _notify_whatsapp_admin(title: str, message: str) -> None:
    """Manda o alerta critical no WhatsApp do operador — best-effort, nunca levanta.

    Limitação conhecida (documentada na spec): free-form só entrega com a janela de
    24h do admin aberta; o canal GARANTIDO é o e-mail do Sentry. ADMIN_ALERT_PHONE
    vazio = feature desligada (skip silencioso). Imports de channels/registry são
    tardios para não criar ciclo (alerts é importado por módulos de baixo nível).
    """
    try:
        if os.environ.get("REHEARSAL_MODE", "").lower() == "true":
            return  # rehearsal não acorda o operador de madrugada por incidente fake
        phone = (os.environ.get("ADMIN_ALERT_PHONE") or "").strip()
        if not phone:
            return  # feature off — skip silencioso
        from app.channels.service import get_active_channel, get_channel_by_id
        from app.whatsapp.registry import get_provider

        channel = None
        channel_id = (os.environ.get("ALERT_CHANNEL_ID") or "").strip()
        if channel_id:
            channel = get_channel_by_id(channel_id)
        if not channel:
            channel = get_active_channel()
        if not channel:
            logger.warning("[ALERT] nenhum canal disponível para alerta WhatsApp ao admin")
            return
        provider = get_provider(channel)
        body = f"🚨 {title}\n\n{message}"
        # create_system_alert é sync mas costuma rodar dentro de um event loop (worker/
        # webhook). Com loop ativo: agenda task (não bloqueia o caminho do incidente);
        # sem loop (script/cron sync): asyncio.run resolve na hora.
        coro = _send_admin_text(provider, phone, body)
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.warning("[ALERT] despacho WhatsApp ao admin falhou (seguindo sem): %s", exc)


async def fire_billing_alert(errors: list) -> None:
    """Cria alerta de billing no banco (dedup: 1 por hora). Aparece como popup no CRM."""
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    try:
        existing = (
            sb.table("system_alerts")
            .select("id")
            .eq("type", "billing_payment_issue")
            .eq("resolved", False)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        if existing.data:
            return
    except Exception as exc:
        logger.error("[ALERT] Failed to check existing billing alert: %s", exc)

    title = "Pagamento pendente na conta WhatsApp"
    message = (
        "Mensagens estão falhando com erro 131042 (Business eligibility payment issue). "
        "Acesse o Business Manager da Meta e quite o débito para retomar os envios."
    )
    logger.critical("[ALERT][BILLING] %s", message)
    create_system_alert(
        "billing_payment_issue", title, message,
        severity="critical",
        metadata={"meta_errors": errors},
    )
