import asyncio
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_BILLING_ERROR_CODE = 131042

# Meta rejeita \n, \r, \t e 4+ espaços consecutivos em body_parameters de template
# (WABA_BODY_PARAM_INVALID_FORMAT). Colapsa para 1 espaço p/ ficar bem abaixo do teto.
_TEMPLATE_VAR_WHITESPACE_RE = re.compile(r"[\s]+")
# Ceilings folgados p/ nunca colidir com o limite de 1024 chars/param da Meta.
_TEMPLATE_VAR_MAX_TITLE = 200
_TEMPLATE_VAR_MAX_BODY = 800


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


# Tipos de alerta critical que disparam WhatsApp ao admin por default.
# Restrito ao domínio "LLM não vai atender" (o incidente que o admin precisa acionar
# 24/7): llm_down (Gemini caiu / 429 prepay depleted / 5xx / timeout) e
# llm_budget_exceeded (kill-switch interno). Outros críticos (handoff_sla_*,
# ai_unresponsive, billing_payment_issue) seguem gravando em system_alerts e Sentry
# — não acordam o admin no WhatsApp fora do horário comercial. Override via
# WHATSAPP_ADMIN_ALERT_TYPES=csv (ex.: llm_down,billing_payment_issue).
_DEFAULT_WHATSAPP_ADMIN_ALERT_TYPES = "llm_down,llm_budget_exceeded"


def _whatsapp_admin_allowed_types() -> set[str]:
    """Allowlist de types que disparam WhatsApp ao admin.

    Lê `WHATSAPP_ADMIN_ALERT_TYPES` (CSV, whitespace tolerado); vazio ou não setado
    cai no default. Nunca retorna set vazio — vazio silencioso quebraria alertas
    críticos legítimos; se o operador quer desligar, seta ADMIN_ALERT_PHONE="".
    """
    raw = (os.environ.get("WHATSAPP_ADMIN_ALERT_TYPES") or "").strip()
    if not raw:
        raw = _DEFAULT_WHATSAPP_ADMIN_ALERT_TYPES
    parsed = {t.strip() for t in raw.split(",") if t.strip()}
    return parsed or {t.strip() for t in _DEFAULT_WHATSAPP_ADMIN_ALERT_TYPES.split(",")}


def _notify_external(type: str, title: str, message: str, severity: str) -> None:
    """Despacha o alerta para fora do CRM (wartime T2, 10/07).

    Roteamento por severidade:
      - critical → Sentry (level=error; e-mail do free tier é o canal garantido)
                   + WhatsApp ao admin — SÓ para types em _whatsapp_admin_allowed_types().
      - warning  → só Sentry (level=warning).
      - demais   → nada (info/error legado continuam sendo só banner do CRM).

    Fail-soft ABSOLUTO: esta função roda no caminho de alerta de incidente — se ela
    levantar, piora o próprio incidente que está reportando. Nenhuma exceção escapa.
    """
    try:
        if severity not in ("critical", "warning"):
            return
        _notify_sentry(type, title, message, severity)
        if severity == "critical" and type in _whatsapp_admin_allowed_types():
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


def _sanitize_template_variable(text: str, max_len: int) -> str:
    """Prepara uma string p/ virar body_parameter de template Meta.

    Meta rejeita variáveis com \\n, \\r, \\t ou 4+ espaços consecutivos
    (WABA_BODY_PARAM_INVALID_FORMAT). Colapsa qualquer whitespace pra 1 espaço,
    tira as pontas e trunca com reticências se passar do teto. Vazio → "-" (Meta
    também rejeita string vazia).
    """
    if not text:
        return "-"
    collapsed = _TEMPLATE_VAR_WHITESPACE_RE.sub(" ", str(text)).strip()
    if not collapsed:
        return "-"
    if len(collapsed) > max_len:
        collapsed = collapsed[: max_len - 1].rstrip() + "…"
    return collapsed


async def _send_admin_notification(
    provider,
    phone: str,
    title: str,
    message: str,
    template_name: str | None,
    template_language: str,
) -> None:
    """Envio awaitable com try próprio — a task agendada nunca morre com exceção solta.

    Se `template_name` informado: tenta send_template primeiro (funciona fora da
    janela de 24h se o template estiver aprovado). Qualquer falha (não aprovado,
    rejeitado, provider quebrado) cai no send_text como cinto de segurança — pelo
    menos entrega dentro da janela de 24h. Ambos os caminhos são fail-soft.
    """
    if template_name:
        try:
            components = [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": _sanitize_template_variable(title, _TEMPLATE_VAR_MAX_TITLE)},
                    {"type": "text", "text": _sanitize_template_variable(message, _TEMPLATE_VAR_MAX_BODY)},
                ],
            }]
            await provider.send_template(
                phone,
                template_name,
                components=components,
                language_code=template_language,
            )
            logger.info(
                "[ALERT] alerta critical enviado via template %s (%s...)",
                template_name, phone[:6],
            )
            return
        except Exception as exc:
            logger.warning(
                "[ALERT] template %s falhou (%s) — caindo para send_text",
                template_name, exc,
            )
    try:
        body = f"🚨 {title}\n\n{message}"
        await provider.send_text(phone, body)
        logger.info("[ALERT] alerta critical enviado ao WhatsApp do admin (%s...)", phone[:6])
    except Exception as exc:
        logger.warning("[ALERT] envio WhatsApp ao admin falhou (best-effort): %s", exc)


def _notify_whatsapp_admin(title: str, message: str) -> None:
    """Manda o alerta critical no WhatsApp do operador — best-effort, nunca levanta.

    Entrega garantida fora da janela de 24h SÓ com template utility aprovado
    (ADMIN_ALERT_TEMPLATE_NAME apontando para um template APPROVED pela Meta).
    Sem template, cai em send_text free-form — só entrega DENTRO da janela de 24h;
    para casos de exaustão longa (madrugada, fds sem contato do admin), o canal
    garantido segue sendo o e-mail do Sentry.

    ADMIN_ALERT_PHONE vazio = feature desligada (skip silencioso). Imports de
    channels/registry são tardios para não criar ciclo (alerts é importado por
    módulos de baixo nível).
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
        # Template UTILITY aprovado pela Meta é o ÚNICO canal garantido fora da janela
        # de 24h do admin (send_text free-form não entrega). Se ADMIN_ALERT_TEMPLATE_NAME
        # não estiver setado, mantém comportamento antigo (só send_text).
        template_name = (os.environ.get("ADMIN_ALERT_TEMPLATE_NAME") or "").strip() or None
        template_language = (os.environ.get("ADMIN_ALERT_TEMPLATE_LANGUAGE") or "pt_BR").strip() or "pt_BR"
        # create_system_alert é sync mas costuma rodar dentro de um event loop (worker/
        # webhook). Com loop ativo: agenda task (não bloqueia o caminho do incidente);
        # sem loop (script/cron sync): asyncio.run resolve na hora.
        coro = _send_admin_notification(provider, phone, title, message, template_name, template_language)
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
