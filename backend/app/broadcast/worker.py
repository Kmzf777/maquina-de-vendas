import asyncio
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta

import httpx

from app.config import get_settings
from app.db.supabase import get_supabase
from app.whatsapp.registry import get_provider
from app.channels.service import get_channel_by_id
from app.broadcast.service import (
    get_pending_broadcast_leads,
    mark_broadcast_lead_sent,
    mark_broadcast_lead_failed,
    increment_broadcast_sent,
    increment_broadcast_failed,
    save_broadcast_lead_wamid,
    requeue_broadcast_lead,
)
from app.conversations.service import get_or_create_conversation, update_conversation, save_message
from app.templates.intent import dispatch_metadata, classify_template_intent, COLD_REACTIVATION
from app.leads.service import (
    update_lead, record_dispatch_note, is_lead_blacklisted, resolve_send_target,
    lead_has_active_relationship,
)
from app.follow_up.scheduler import process_due_followups, check_meta_channel_health

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"
_META_API_BASE = "https://graph.facebook.com/v21.0"
_BILLING_ERROR_CODE = 131042

# Cadência do loop principal. Era 5s — com ~8-12 queries REST por tick, 24/7,
# o polling ocioso respondia por boa parte do estouro de Egress do Supabase
# (cota Free de 5GB/mês). Nenhum job do loop exige latência de segundos:
# broadcasts agendados, cadência, follow-ups e memórias têm granularidade de
# minutos/horas; o envio em si roda DENTRO de process_single_broadcast com
# sleep próprio por lead. Ao adicionar jobs novos ao loop (ex.: Etapa 3-4 do
# watchdog/Frente B), dimensionar para esta latência base.
WORKER_TICK_SECONDS = 30

# Lotes de lead_ids por query no reconcile (limite prático de URL do PostgREST
# com UUIDs em `in.(...)`).
_RECONCILE_ID_CHUNK = 100

# Confirmação de entrega assíncrona. A Meta aceita o send (HTTP 200 + wamid,
# message_status="accepted") e só confirma a entrega física depois, via webhook de
# status. Uma mensagem que fica em "accepted" além deste limite provavelmente nunca
# recebeu callback — o canal está "silencioso" (sem webhook de status assinado para o
# phone_number_id). O corte é folgado: callbacks reais chegam em segundos.
DELIVERY_CONFIRMATION_TIMEOUT_MINUTES = 30
# Janela de varredura (piso) — evita reprocessar histórico antigo a cada tick.
_DELIVERY_LIMBO_LOOKBACK_HOURS = 24
# Teto de linhas por tick (defesa de Egress; paridade com reconcile_broadcast_replies).
_DELIVERY_LIMBO_LIMIT = 200
# A partir de quantas mensagens não confirmadas no MESMO canal, num tick, disparamos
# o alerta de "canal silencioso" (webhook de status quebrado).
_SILENT_CHANNEL_ALERT_THRESHOLD = 3

logger = logging.getLogger(__name__)


async def _preflight_channel_check(channel: dict) -> bool:
    """Live GET to Meta API before each broadcast batch.

    Returns True (proceed) if the channel responds OK.
    Returns False if the channel has an auth error.
    On network error or non-auth failure returns True optimistically — billing
    issues are caught in real-time during the per-lead send and handled there.

    Side effect: auto-resolves open billing alerts when Meta API responds OK,
    so the user doesn't have to wait for the hourly health check after fixing payment.
    """
    config = channel.get("provider_config") or {}
    phone_number_id = config.get("phone_number_id", "")
    access_token = config.get("access_token", "")
    if not phone_number_id or not access_token:
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_META_API_BASE}/{phone_number_id}",
                params={"fields": "id,quality_rating"},
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if resp.is_success:
            # Channel reachable — auto-resolve stale billing alerts so retries are unblocked
            try:
                sb = get_supabase()
                sb.table("system_alerts").update({
                    "resolved": True,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }).eq("type", "billing_payment_issue").eq("resolved", False).execute()
            except Exception:
                pass
            return True

        error = resp.json().get("error", {})
        logger.critical(
            "[BROADCAST] Pre-flight Meta check failed code=%s: %s",
            error.get("code"), error.get("message"),
        )
        # Token expired/invalid — fire alert so admin notices
        if error.get("code") in (190, 102):
            try:
                from app.alerts.service import create_system_alert
                create_system_alert(
                    "token_expired",
                    f"Token Meta expirado — canal {channel.get('name')}",
                    error.get("message", "Token inválido"),
                    severity="critical",
                    metadata={"channel_id": channel.get("id")},
                )
            except Exception:
                pass
        return False

    except Exception as exc:
        logger.warning("[BROADCAST] Pre-flight: falha ao contactar Meta (prosseguindo): %s", exc)
        return True  # network error — proceed optimistically

def _lead_first_name(lead: dict) -> str:
    """Primeiro nome real do lead, ou "você" se for handle/username/vazio.

    Evita "Falo com Brunor_barista neste número?" — handle vira "Falo com você...".
    """
    from app.leads.service import sanitize_display_name
    clean = sanitize_display_name(lead.get("name"))
    return clean.split()[0] if clean else "você"


def _lead_full_name(lead: dict) -> str:
    from app.leads.service import sanitize_display_name
    return sanitize_display_name(lead.get("name")) or "você"


# Dynamic variable tokens that get resolved from the lead record at send time.
_LEAD_FIELD_TOKENS = {
    # New tokens (used by smart broadcast modal)
    "{{primeiro_nome}}": _lead_first_name,
    "{{nome_completo}}": _lead_full_name,
    "{{telefone}}":      lambda lead: lead.get("phone") or "",
    "{{empresa}}":       lambda lead: lead.get("company") or lead.get("nome_fantasia") or "",
    # Legacy tokens kept for backward compatibility
    "{{first_name}}":    _lead_first_name,
    "{{lead_name}}":     _lead_full_name,
    "{{phone}}":         lambda lead: lead.get("phone") or "",
}


def _resolve_value(value: str, lead: dict) -> str:
    for token, resolver in _LEAD_FIELD_TOKENS.items():
        if value == token:
            return resolver(lead)
    return value


def _apply_variables(text: str, template_variables: dict, lead: dict) -> str:
    params_type = template_variables.get("__params_type__", "named")
    body_vars = {
        k: v for k, v in template_variables.items()
        if not str(k).startswith("__") and k != "components"
    }
    if params_type == "positional":
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(str(x[0]).lstrip("0") or "0") if str(x[0]).isdigit() else 999,
        )
        for i, (_, v) in enumerate(ordered, start=1):
            text = text.replace(f"{{{{{i}}}}}", _resolve_value(str(v), lead))
    else:
        for k, v in body_vars.items():
            text = text.replace(f"{{{{{k}}}}}", _resolve_value(str(v), lead))
    return text


async def _render_template_body(template_name: str, template_variables: dict, lead: dict, channel: dict | None = None) -> str:
    """Render template BODY text. Tries local DB first, falls back to Meta API and auto-syncs."""
    # 1. Try local message_templates table
    try:
        sb = get_supabase()
        result = sb.table("message_templates").select("components").eq("name", template_name).limit(1).execute()
        if result.data:
            components = result.data[0].get("components", [])
            body = next((c for c in components if c.get("type") == "BODY"), None)
            if body:
                return _apply_variables(body.get("text", ""), template_variables, lead)
    except Exception as e:
        logger.warning(f"[BROADCAST] Local template lookup failed for {template_name}: {e}")

    # 2. Fallback: fetch from Meta API and auto-sync into local DB
    if channel:
        try:
            config = channel.get("provider_config", {})
            waba_id = config.get("waba_id") or os.environ.get("META_WABA_ID", "")
            access_token = config.get("access_token") or os.environ.get("META_ACCESS_TOKEN", "")
            if waba_id and access_token:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
                        params={"name": template_name},
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    data = resp.json().get("data", [])
                    if data:
                        components = data[0].get("components", [])
                        body = next((c for c in components if c.get("type") == "BODY"), None)
                        if body:
                            rendered = _apply_variables(body.get("text", ""), template_variables, lead)
                            try:
                                sb = get_supabase()
                                sb.table("message_templates").insert({
                                    "channel_id": channel["id"],
                                    "name": template_name,
                                    "language": data[0].get("language", "pt_BR"),
                                    "requested_category": data[0].get("category", "UTILITY"),
                                    "category": data[0].get("category", "UTILITY"),
                                    "components": components,
                                    "meta_template_id": data[0].get("id"),
                                    "status": "approved",
                                }).execute()
                                logger.info(f"[BROADCAST] Auto-synced template {template_name} to local DB")
                            except Exception as sync_err:
                                logger.warning(f"[BROADCAST] Auto-sync failed for {template_name}: {sync_err}")
                            return rendered
        except Exception as e:
            logger.warning(f"[BROADCAST] Meta API template lookup failed for {template_name}: {e}")

    return f"[Template: {template_name}]"


def _build_template_components(template_variables: dict, lead: dict) -> list | None:
    """Build Meta template components from stored variable mappings.

    Supports:
    - Named params: {param_name: token_or_text, ...}
    - Positional params: {"1": token, "2": token, ...} with __params_type__="positional"
    - Media headers: __header_type__ = IMAGE|VIDEO|DOCUMENT, __header_url__ = url
    Reserved keys starting with __ control behaviour and are excluded from body params.
    Old broadcasts without __params_type__ default to named (backward compat).
    """
    if not template_variables:
        return None

    params_type = template_variables.get("__params_type__", "named")
    header_type = template_variables.get("__header_type__")
    header_url = template_variables.get("__header_url__")

    # Exclude reserved keys and legacy "components" key from body variables
    body_vars = {
        k: v for k, v in template_variables.items()
        if not str(k).startswith("__") and k != "components"
    }

    components: list = []

    # Header component — media types only (TEXT header has no parameters)
    if header_type in ("IMAGE", "VIDEO", "DOCUMENT") and header_url:
        media_key = header_type.lower()
        components.append({
            "type": "header",
            "parameters": [{"type": media_key, media_key: {"link": header_url}}],
        })

    # Body component
    if params_type == "positional":
        # Sort by numeric key (1, 2, 3…); non-numeric keys sort last
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(str(x[0]).lstrip("0") or "0") if str(x[0]).isdigit() else 999,
        )
        parameters = [
            {"type": "text", "text": _resolve_value(str(v), lead)}
            for _, v in ordered
        ]
    else:
        # Named params (default — also handles legacy broadcasts)
        parameters = [
            {
                "type": "text",
                "parameter_name": k,
                "text": _resolve_value(str(v), lead),
            }
            for k, v in body_vars.items()
        ]

    if parameters:
        components.append({"type": "body", "parameters": parameters})

    return components if components else None


def _build_conv_updates(broadcast: dict) -> dict:
    """Builds conversation-level updates for a broadcast dispatch.

    Only status and agent_profile_id — ai_enabled lives on the lead now.
    """
    conv_updates: dict = {"status": "template_sent"}
    if broadcast.get("agent_profile_id"):
        conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
    return conv_updates


def _pipeline_name_to_segment(pipeline_name: str | None) -> str | None:
    """Mapeia o nome do pipeline-alvo do broadcast → segmento outbound da Valéria.

    Reusa o padrão de substring de _resolve_lp_pipeline. Casa nomes como
    'Valeria - Atacado', 'João - Private Label', 'Arthur - Exportação'. Pipelines sem
    segmento claro (ex.: 'Importação Leads Frios', 'Recuperação') → None.
    """
    n = (pipeline_name or "").lower()
    if "atacado" in n:
        return "atacado"
    if "private label" in n or "marca propria" in n or "marca própria" in n:
        return "private_label"
    if "exporta" in n:           # exportação / exportacao
        return "exportacao"
    if "consumo" in n:
        return "consumo"
    return None


def _build_lead_updates(
    broadcast: dict,
    channel: dict | None,
    lead: dict,
    campaign_segment: str | None = None,
) -> dict:
    """Monta o update do lead no disparo: ai_enabled (+ human_control) e, quando a campanha
    tem segmento-alvo, persiste metadata.campaign_segment (mergeando o metadata existente).

    O segmento é gravado mesmo em canal humano — serve de inteligência futura para a Valéria
    quando/se a IA reassumir. Sem segmento, NÃO toca o metadata (evita sobrescrever).
    """
    ai_enabled = _broadcast_ai_enabled(broadcast, channel=channel)
    updates: dict = {"ai_enabled": ai_enabled}
    if ai_enabled:
        updates["human_control"] = False
    if campaign_segment:
        meta = dict(lead.get("metadata") or {})
        meta["campaign_segment"] = campaign_segment
        updates["metadata"] = meta
    return updates


def _broadcast_ai_enabled(broadcast: dict, channel: dict | None = None) -> bool:
    """Returns the ai_enabled value to set on the lead for this broadcast.

    Invariant: human channel → always False; ai channel with agent → True.
    """
    if channel and channel.get("mode", "ai") == "human":
        return False
    return bool(broadcast.get("agent_profile_id"))


def _blacklist_guardrail(lead: dict) -> str | None:
    """CAMADA 2 — guardrail rígido no momento do envio.

    Re-checa a blacklist FRESCA (opt-out / pipeline Blacklist) no milissegundo antes do
    disparo, pegando o lead que deu opt-out ENTRE a criação da campanha e o envio (a Camada 1
    filtra na criação, mas a janela pode ser de horas). Retorna o motivo do skip (string) se o
    lead estiver na blacklist; None se está liberado. Delegação pura a is_lead_blacklisted —
    unit-testável sem rodar o loop de envio.
    """
    if is_lead_blacklisted(lead.get("id")):
        return "blacklist: opt-out ou pipeline Blacklist"
    return None


def _parse_ts(value: str) -> datetime:
    """Timestamp do Supabase → datetime aware (sufixo `Z` ou `+00:00`)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reconcile_broadcast_replies() -> None:
    """Catch-up job: fills first_replied_at for leads that replied but webhook failed.

    Scans broadcast_leads sent in the last 48h (minus the last 2min to avoid
    racing with the webhook). Limit 200 leads per tick.

    As respostas são buscadas em LOTE (uma query de `messages` por chunk de
    lead_ids) e o corte por janela individual (sent_at → sent_at+48h) é feito
    em Python. O padrão anterior — 1 query por lead pendente, a cada tick —
    era o maior consumidor isolado de Egress do banco (5,8M chamadas/trimestre
    no pg_stat_statements de produção).
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=48)).isoformat()
    window_end = (now - timedelta(minutes=2)).isoformat()

    pending = (
        sb.table("broadcast_leads")
        .select("id, lead_id, sent_at")
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", window_start)
        .lte("sent_at", window_end)
        .limit(200)
        .execute()
    )
    if not pending.data:
        return

    # Piso/teto globais do lote: menor sent_at e maior sent_at+48h entre os
    # pendentes. O refinamento por lead acontece em Python, abaixo.
    sent_dts = {bl["id"]: _parse_ts(bl["sent_at"]) for bl in pending.data}
    batch_floor = min(sent_dts.values()).isoformat()
    batch_ceil = (max(sent_dts.values()) + timedelta(hours=48)).isoformat()

    # Mensagens de user desses leads, ordenadas asc — a PRIMEIRA resposta na
    # janela é o valor gravado. O limit é a defesa explícita contra o teto
    # server-side do PostgREST; ordenar asc é a direção segura: truncar só
    # atrasa a reconciliação de respostas mais novas para o próximo tick.
    lead_ids = sorted({bl["lead_id"] for bl in pending.data})
    replies_by_lead: dict[str, list[str]] = {}
    for i in range(0, len(lead_ids), _RECONCILE_ID_CHUNK):
        chunk = lead_ids[i : i + _RECONCILE_ID_CHUNK]
        try:
            rows = (
                sb.table("messages")
                .select("lead_id, created_at")
                .in_("lead_id", chunk)
                .eq("role", "user")
                .gt("created_at", batch_floor)
                .lte("created_at", batch_ceil)
                .order("created_at")
                .limit(1000)
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("[BROADCAST] reconcile: falha no lote de replies: %s", e)
            continue
        for row in rows:
            replies_by_lead.setdefault(row["lead_id"], []).append(row["created_at"])

    reconciled = 0
    for bl in pending.data:
        try:
            sent_at_dt = sent_dts[bl["id"]]
            reply_window_end = sent_at_dt + timedelta(hours=48)
            for created_at in replies_by_lead.get(bl["lead_id"], []):
                created_dt = _parse_ts(created_at)
                if sent_at_dt < created_dt <= reply_window_end:
                    sb.table("broadcast_leads").update({
                        "first_replied_at": created_at,
                    }).eq("id", bl["id"]).execute()
                    reconciled += 1
                    break
        except Exception as e:
            logger.warning("[BROADCAST] reconcile error for bl=%s: %s", bl.get("id"), e)

    if reconciled:
        logger.info(
            "[BROADCAST] reconcile_broadcast_replies: %d leads atualizados",
            reconciled,
        )


def reconcile_delivery_timeouts() -> None:
    """Varre mensagens presas em "accepted" (aceitas pela Meta, sem callback de entrega).

    A Meta responde ao send com HTTP 200 + wamid e message_status="accepted" — só um
    aviso de que a mensagem entrou na fila. A confirmação de entrega vem depois, num
    webhook de status que promove delivery_status accepted→sent→delivered→read (ou
    failed). Quando esse webhook NUNCA chega — porque o phone_number_id não tem a
    assinatura de status ativa (canal "silencioso") — a mensagem ficaria eternamente
    como "accepted", mascarando uma não-entrega como se fosse sucesso.

    Esta rotina fecha o limbo: mensagens em "accepted" há mais de
    DELIVERY_CONFIRMATION_TIMEOUT_MINUTES (e dentro da janela de lookback) são marcadas
    como "undelivered" (entrega não confirmada). Se um mesmo canal acumula várias, um
    alerta de canal silencioso é criado (dedup 1/h) para a gestão religar o webhook.

    Não toca broadcast_leads nem os contadores do broadcast: o estado de fila
    (sent/delivered/failed) e a idempotência de reenvio continuam intactos. A verdade
    visível ao operador vive em messages.delivery_status + no alerta.
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    timeout_ceil = (now - timedelta(minutes=DELIVERY_CONFIRMATION_TIMEOUT_MINUTES)).isoformat()
    window_floor = (now - timedelta(hours=_DELIVERY_LIMBO_LOOKBACK_HOURS)).isoformat()

    try:
        stuck = (
            sb.table("messages")
            .select("id, wamid, conversation_id, created_at")
            .eq("delivery_status", "accepted")
            .filter("wamid", "not.is", "null")
            .gte("created_at", window_floor)
            .lt("created_at", timeout_ceil)
            .limit(_DELIVERY_LIMBO_LIMIT)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning("[DELIVERY] reconcile_delivery_timeouts: falha ao buscar limbo: %s", e)
        return

    if not stuck:
        return

    msg_ids = [m["id"] for m in stuck]
    try:
        sb.table("messages").update({"delivery_status": "undelivered"}).in_("id", msg_ids).execute()
    except Exception as e:
        logger.warning("[DELIVERY] reconcile_delivery_timeouts: falha ao marcar undelivered: %s", e)
        return

    logger.warning(
        "[DELIVERY] %d mensagem(ns) sem confirmação de entrega após %dmin → undelivered",
        len(msg_ids), DELIVERY_CONFIRMATION_TIMEOUT_MINUTES,
    )

    # Atribui cada mensagem ao seu canal (via conversation) para detectar canal silencioso.
    conv_ids = sorted({m["conversation_id"] for m in stuck if m.get("conversation_id")})
    if not conv_ids:
        return
    channel_by_conv: dict[str, str] = {}
    for i in range(0, len(conv_ids), _RECONCILE_ID_CHUNK):
        chunk = conv_ids[i : i + _RECONCILE_ID_CHUNK]
        try:
            rows = (
                sb.table("conversations")
                .select("id, channel_id")
                .in_("id", chunk)
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("[DELIVERY] reconcile: falha ao mapear conversa→canal: %s", e)
            continue
        for r in rows:
            if r.get("channel_id"):
                channel_by_conv[r["id"]] = r["channel_id"]

    per_channel: dict[str, int] = {}
    for m in stuck:
        ch = channel_by_conv.get(m.get("conversation_id"))
        if ch:
            per_channel[ch] = per_channel.get(ch, 0) + 1

    for channel_id, count in per_channel.items():
        if count >= _SILENT_CHANNEL_ALERT_THRESHOLD:
            _alert_silent_channel(sb, channel_id, count)


def _alert_silent_channel(sb, channel_id: str, count: int) -> None:
    """Cria alerta de canal silencioso (webhook de status ausente). Dedup: 1/h por canal."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        existing = (
            sb.table("system_alerts")
            .select("id")
            .eq("type", "channel_delivery_silent")
            .eq("resolved", False)
            .gte("created_at", cutoff)
            .contains("metadata", {"channel_id": channel_id})
            .limit(1)
            .execute()
        )
        if existing.data:
            return
    except Exception as e:
        logger.warning("[DELIVERY] falha ao checar alerta de canal silencioso: %s", e)

    channel_name = channel_id
    try:
        ch = get_channel_by_id(channel_id)
        if ch:
            channel_name = ch.get("name") or channel_id
    except Exception:
        pass

    try:
        from app.alerts.service import create_system_alert
        create_system_alert(
            "channel_delivery_silent",
            f"Canal sem confirmação de entrega — {channel_name}",
            (
                f"{count} mensagem(ns) enviadas pelo canal '{channel_name}' foram aceitas pela "
                f"Meta mas nunca receberam webhook de status (entrega não confirmada). "
                f"Provável assinatura de webhook de status inativa para este phone_number_id. "
                f"Rode backend/scripts/resubscribe_webhook_phone.py e verifique o override de "
                f"webhook no Meta App Dashboard."
            ),
            severity="critical",
            metadata={"channel_id": channel_id, "stuck_count": count},
        )
        logger.critical("[DELIVERY][SILENT] Canal %s silencioso — %d mensagens não confirmadas", channel_name, count)
    except Exception as e:
        logger.warning("[DELIVERY] falha ao criar alerta de canal silencioso: %s", e)


def _toggle_br_ninth_digit(number: str | None) -> str | None:
    """Alterna a presença do 9º dígito de um móvel BR em E.164 (sem '+').

    13 díg. com 9  → remove o 9 (12 díg.);  12 díg. sem 9 → injeta o 9 (13 díg.).
    Retorna None se não for um móvel BR reconhecível (não há forma alternativa a tentar).
    """
    if not number:
        return None
    d = re.sub(r"\D", "", number)
    if len(d) == 13 and d.startswith("55") and d[4] == "9":
        return d[:4] + d[5:]
    if len(d) == 12 and d.startswith("55"):
        return d[:4] + "9" + d[4:]
    return None


async def retry_undelivered_cold_sends() -> None:
    """Dupla tentativa ESTRUTURADA: uma única retentativa alternando o 9º dígito.

    Quando reconcile_delivery_timeouts vira uma mensagem de disparo de 'accepted' para
    'undelivered' (a Meta aceitou mas nunca confirmou entrega), este job reenvia UMA vez
    para a forma alternada do número — cobrindo o caso em que a registration real do
    destino difere do formato que tentamos. Trava dupla contra duplicação: só age quando
    `delivered_at IS NULL` e claima atomicamente `delivery_retried` (false→true), de modo
    que jamais há mais de uma retentativa nem reenvio a quem já recebeu.
    """
    sb = get_supabase()
    floor = (datetime.now(timezone.utc) - timedelta(hours=_DELIVERY_LIMBO_LOOKBACK_HOURS)).isoformat()

    try:
        undelivered = (
            sb.table("messages")
            .select("wamid")
            .eq("delivery_status", "undelivered")
            .filter("wamid", "not.is", "null")
            .gte("created_at", floor)
            .limit(100)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning("[DELIVERY][RETRY] falha ao buscar undelivered: %s", e)
        return
    wamids = sorted({m["wamid"] for m in undelivered if m.get("wamid")})
    if not wamids:
        return

    for i in range(0, len(wamids), _RECONCILE_ID_CHUNK):
        chunk = wamids[i : i + _RECONCILE_ID_CHUNK]
        try:
            bls = (
                sb.table("broadcast_leads")
                .select(
                    "id, broadcast_id, lead_id, wamid, "
                    "leads!inner(id, phone, wa_id), "
                    "broadcasts!inner(channel_id, template_name, template_language_code, template_variables)"
                )
                .in_("wamid", chunk)
                .eq("delivery_retried", False)
                .is_("delivered_at", "null")
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("[DELIVERY][RETRY] falha ao buscar broadcast_leads: %s", e)
            continue

        for bl in bls:
            await _retry_single_undelivered(sb, bl)


async def _retry_single_undelivered(sb, bl: dict) -> None:
    lead = bl.get("leads") or {}
    broadcast = bl.get("broadcasts") or {}

    alt_target = _toggle_br_ninth_digit(lead.get("phone"))
    if not alt_target:
        return

    # Claim atômico: false→true guardado por delivered_at IS NULL. Se não afetar linha,
    # outro tick já retentou ou a entrega foi confirmada nesse meio-tempo — aborta.
    claim = (
        sb.table("broadcast_leads")
        .update({"delivery_retried": True})
        .eq("id", bl["id"])
        .eq("delivery_retried", False)
        .is_("delivered_at", "null")
        .execute()
    )
    if not claim.data:
        return

    channel_id = broadcast.get("channel_id")
    channel = get_channel_by_id(channel_id) if channel_id else None
    if not channel:
        logger.warning("[DELIVERY][RETRY] canal %s ausente — retry abortado p/ bl %s", channel_id, bl["id"])
        return

    try:
        provider = get_provider(channel)
        components = _build_template_components(broadcast.get("template_variables") or {}, lead)
        logger.warning(
            "[DELIVERY][RETRY] reenviando '%s' p/ forma alternada %s (bl=%s, lead=%s)",
            broadcast.get("template_name"), alt_target, bl["id"], lead.get("id"),
        )
        send_response = await provider.send_template(
            to=alt_target,
            template_name=broadcast["template_name"],
            components=components,
            language_code=broadcast.get("template_language_code", "pt_BR"),
        )
        new_wamid = (send_response.get("messages") or [{}])[0].get("id")
        if new_wamid:
            # Reaponta o broadcast_lead para o novo wamid: o callback de entrega desta
            # tentativa passa a mapear aqui (delivered_at ainda NULL → contável).
            sb.table("broadcast_leads").update({"wamid": new_wamid}).eq("id", bl["id"]).execute()
        # Registra a retentativa na conversa (fail-soft) para visibilidade no CRM.
        try:
            conversation = get_or_create_conversation(lead["id"], channel_id)
            if conversation:
                rendered = await _render_template_body(
                    broadcast["template_name"], broadcast.get("template_variables") or {}, lead, channel
                )
                save_message(
                    conversation["id"], lead["id"], "assistant", rendered,
                    sent_by="broadcast", wamid=new_wamid,
                    metadata=dispatch_metadata(broadcast["template_name"], None),
                )
        except Exception as msg_err:
            logger.warning("[DELIVERY][RETRY] falha ao registrar msg da retentativa (bl %s): %s", bl["id"], msg_err)
    except Exception as e:
        logger.warning("[DELIVERY][RETRY] reenvio falhou p/ bl %s (%s): %s", bl["id"], alt_target, e)


async def run_worker():
    """Main worker loop: broadcasts, automation engine, follow-ups."""
    logger.info("Worker started")

    while True:
        try:
            from app.automation.engine import process_due_enrollments
            from app.automation.triggers import check_polling_triggers
            await check_meta_channel_health()
            await process_scheduled_broadcasts()
            await process_broadcasts()
            await check_polling_triggers()
            await process_due_enrollments()
            await process_due_followups()
            # Gatilho A da Camada de Memória: consolida o Dossiê de leads cuja sessão
            # acabou de encerrar (debounced por inatividade + lock no banco).
            from app.agent.memory_manager import process_stale_lead_memories
            await process_stale_lead_memories()
            reconcile_broadcast_replies()
            reconcile_delivery_timeouts()
            await retry_undelivered_cold_sends()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(WORKER_TICK_SECONDS)


async def process_broadcasts():
    """Find running broadcasts and send pending templates."""
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .eq("env_tag", _ENV_TAG)
        .execute()
        .data
    )

    logger.info(f"[DEBUG-BROADCAST] tick — env_tag={_ENV_TAG} running_broadcasts={len(broadcasts)}")
    for broadcast in broadcasts:
        logger.info(f"[DEBUG-BROADCAST] picked broadcast id={broadcast['id']} name={broadcast.get('name')} env_tag={broadcast.get('env_tag')}")
        await process_single_broadcast(broadcast)


async def process_scheduled_broadcasts():
    """Auto-inicia broadcasts cujo scheduled_at já passou."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    broadcasts = (
        sb.table("broadcasts")
        .select("id, name")
        .eq("status", "scheduled")
        .eq("env_tag", _ENV_TAG)
        .lte("scheduled_at", now)
        .execute()
        .data
    )
    for broadcast in broadcasts:
        broadcast_id = broadcast["id"]
        pending_count = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        ) or 0
        if not pending_count:
            logger.error(
                f"[SCHEDULER] broadcast {broadcast_id} sem leads pendentes — marcando como failed"
            )
            sb.table("broadcasts").update({"status": "failed"}).eq("id", broadcast_id).execute()
            continue
        sb.table("broadcasts").update({"status": "running"}).eq("id", broadcast_id).execute()
        logger.info(
            f"[SCHEDULER] broadcast {broadcast_id} ({broadcast.get('name')}) "
            f"iniciado automaticamente — {pending_count} leads"
        )


def _resolve_broadcast_prompt_key(sb, agent_profile_id: str | None) -> str | None:
    """prompt_key (persona) do agent_profile escolhido no broadcast — resolvido 1x por batch.

    Propagado a dispatch_metadata: um disparo sob `valeria_outbound` marca o cold-open como
    cold_reactivation (a escolha do operador é autoridade sobre o nome genérico do template).
    Fail-open: qualquer erro → None (classificação cai no comportamento legado por nome).
    """
    if not agent_profile_id:
        return None
    try:
        res = (
            sb.table("agent_profiles")
            .select("prompt_key")
            .eq("id", agent_profile_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("prompt_key")
    except Exception as exc:
        logger.warning(
            "[BROADCAST] Failed to resolve prompt_key for profile %s: %s", agent_profile_id, exc
        )
    return None


def _has_open_billing_alert(sb) -> bool:
    """True se há um alerta de billing (131042) aberto — mesmo sinal do guard de /start."""
    try:
        res = (
            sb.table("system_alerts")
            .select("id")
            .eq("type", "billing_payment_issue")
            .eq("resolved", False)
            .limit(1)
            .execute()
        )
        # PostgREST sempre devolve lista; só um resultado não-vazio é alerta real.
        return isinstance(res.data, list) and len(res.data) > 0
    except Exception as exc:
        logger.warning("[BROADCAST] Falha ao checar alerta de billing: %s", exc)
        return False


# Janela (dias) do dedup lead+template: o MESMO template reenviado dentro dela é
# pulado (auditoria 08/07, caso Daniel: template idêntico em 04/07 e 08/07 → opt-out).
_TEMPLATE_DEDUP_DAYS = int(os.environ.get("BROADCAST_TEMPLATE_DEDUP_DAYS", "14"))


def _hot_lead_guardrail(lead: dict, broadcast_intent: str) -> str | None:
    """Camada 2 da higiene de lista fria (auditoria 08/07, caso Nayara): lead com
    relacionamento ativo/contato humano recente NÃO recebe disparo FRIO.

    Só se aplica a broadcasts de intent COLD_REACTIVATION — campanhas de reativação
    de clientes (reativacao_*) miram leads quentes DE PROPÓSITO e passam direto.
    Fail-open: erro na checagem nunca bloqueia o envio.
    """
    if broadcast_intent != COLD_REACTIVATION:
        return None
    try:
        if lead_has_active_relationship(lead.get("id")):
            return "lead quente (relacionamento ativo/contato humano <90d) — excluído do disparo frio"
    except Exception as exc:
        logger.warning(
            "[BROADCAST][HOT] checagem de relacionamento falhou p/ %s: %s (fail-open)",
            lead.get("id"), exc,
        )
    return None


def _template_dedup_guardrail(
    lead_id: str | None, template_name: str | None, window_days: int | None = None,
) -> str | None:
    """Pula o envio se ESTE template já foi enviado a ESTE lead dentro da janela.

    Re-blast idêntico em poucos dias queima a lista (caso Daniel, 08/07). Janela
    configurável via BROADCAST_TEMPLATE_DEDUP_DAYS (default 14). Fail-open.
    """
    if not lead_id or not template_name:
        return None
    days = window_days or _TEMPLATE_DEDUP_DAYS
    try:
        sb = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        res = (
            sb.table("broadcast_leads")
            .select("id, broadcasts!inner(template_name)")
            .eq("lead_id", lead_id)
            .eq("status", "sent")
            .eq("broadcasts.template_name", template_name)
            .gte("sent_at", cutoff)
            .limit(1)
            .execute()
        )
        # lista não-vazia (PostgREST devolve list) — truthiness cru dispararia com mocks.
        if isinstance(res.data, list) and res.data:
            return f"dedup: template '{template_name}' já enviado a este lead há menos de {days}d"
    except Exception as exc:
        logger.warning(
            "[BROADCAST][DEDUP] checagem de template repetido falhou p/ %s: %s (fail-open)",
            lead_id, exc,
        )
    return None


async def process_single_broadcast(broadcast: dict):
    sb = get_supabase()
    broadcast_id = broadcast["id"]

    # Defense-in-depth: o 131042 chega assíncrono (webhook), então entre o 1º débito e o
    # webhook pausar o broadcast há uma janela onde o worker seguiria disparando. Aqui,
    # a cada lote, se já existe alerta de billing aberto, auto-aborta e pausa — fechando
    # essa janela sem depender de o webhook por-wamid ter chegado. Paridade com /start.
    if _has_open_billing_alert(sb):
        logger.critical(
            "[BROADCAST][BILLING] Alerta de billing aberto — pausando broadcast %s (lote não enviado)",
            broadcast_id,
        )
        sb.table("broadcasts").update({"status": "paused"}).eq("id", broadcast_id).execute()
        return

    # Pre-flight: live check on Meta API — auto-resolves stale billing alerts when channel is OK.
    # Billing issues not detectable via GET are caught in real-time during per-lead send (below).
    try:
        preflight_channel_id = broadcast.get("channel_id")
        if preflight_channel_id:
            preflight_channel = get_channel_by_id(preflight_channel_id)
            if preflight_channel and preflight_channel.get("provider") == "meta_cloud":
                if not await _preflight_channel_check(preflight_channel):
                    logger.critical(
                        "[BROADCAST] Abortando broadcast '%s' (%s) — canal Meta indisponível (token/auth)",
                        broadcast.get("name"), broadcast_id,
                    )
                    sb.table("broadcasts").update({"status": "paused"}).eq("id", broadcast_id).execute()
                    return
    except Exception as exc:
        logger.error("[BROADCAST] Falha no pre-flight check para broadcast %s: %s", broadcast_id, exc)

    # Recover leads stuck in 'processing' for over 5 minutes (worker crash/restart).
    # If wamid is set, the message reached Meta — mark as sent instead of re-queuing
    # to avoid sending the same template twice.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    sb.table("broadcast_leads").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("broadcast_id", broadcast_id).eq("status", "processing").lt(
        "claimed_at", cutoff
    ).filter("wamid", "not.is", "null").execute()
    sb.table("broadcast_leads").update({"status": "pending", "claimed_at": None}).eq(
        "broadcast_id", broadcast_id
    ).eq("status", "processing").lt("claimed_at", cutoff).filter("wamid", "is", "null").execute()

    # Pre-fetch pipeline_id for stage move once per batch — move_to_stage_id is the same for
    # every lead, so querying pipeline_stages inside the per-lead loop is wasteful.
    move_to_stage_id: str | None = broadcast.get("move_to_stage_id")
    target_pipeline_id: str | None = None
    if move_to_stage_id:
        try:
            stage_row = sb.table("pipeline_stages").select("pipeline_id").eq("id", move_to_stage_id).limit(1).execute()
            if stage_row.data:
                target_pipeline_id = stage_row.data[0]["pipeline_id"]
            else:
                logger.warning(
                    "[BROADCAST] move_to_stage_id %s not found in pipeline_stages — stage move skipped for broadcast %s",
                    move_to_stage_id, broadcast_id,
                )
        except Exception as stage_err:
            logger.warning("[BROADCAST] Failed to fetch pipeline for move_to_stage_id %s: %s", move_to_stage_id, stage_err)

    # Segmento da campanha (Épico A4): derivado do nome do pipeline-alvo, uma vez por batch.
    # Persistido em lead.metadata.campaign_segment para a Valéria abrir o 1º turno com a
    # hipótese de segmento (lido em build_outbound_first_turn_context via lead_context).
    campaign_segment: str | None = None
    if target_pipeline_id:
        try:
            pipeline_row = sb.table("pipelines").select("name").eq("id", target_pipeline_id).limit(1).execute()
            if pipeline_row.data:
                campaign_segment = _pipeline_name_to_segment(pipeline_row.data[0].get("name"))
        except Exception as seg_err:
            logger.warning("[BROADCAST] Failed to derive campaign_segment for broadcast %s: %s", broadcast_id, seg_err)

    # Persona (prompt_key) do disparo — resolvida 1x por batch. Torna a escolha outbound do
    # operador autoridade na classificação de intent do cold-open (ver dispatch_metadata).
    broadcast_prompt_key = _resolve_broadcast_prompt_key(sb, broadcast.get("agent_profile_id"))
    # Intent do disparo (1x por batch) — os guardrails de higiene abaixo só travam
    # lead quente em disparo FRIO (cold_reactivation), nunca em reativação intencional.
    broadcast_intent = classify_template_intent(
        broadcast.get("template_name"), broadcast_prompt_key,
    )

    pending_leads = get_pending_broadcast_leads(broadcast_id, limit=10)
    logger.info(f"[DEBUG-BROADCAST] broadcast={broadcast_id} pending_leads={len(pending_leads)}")

    if not pending_leads:
        # Count both pending and processing — don't mark complete while another worker holds claims
        remaining = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .in_("status", ["pending", "processing"])
            .execute()
            .count
        )
        if not remaining:
            sb.table("broadcasts").update({"status": "completed"}).eq("id", broadcast_id).execute()
            logger.info(f"Broadcast {broadcast_id} completed")
        return

    for bl in pending_leads:
        # Atomic claim: only proceeds if this worker wins the race
        claim = (
            sb.table("broadcast_leads")
            .update({"status": "processing", "claimed_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", bl["id"])
            .eq("status", "pending")
            .execute()
        )
        if not claim.data:
            logger.info(f"[BROADCAST] Lead {bl['id']} already claimed by another worker, skipping")
            continue
        # Check if still running
        current = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
        if current["status"] != "running":
            return

        lead = bl["leads"]

        # CAMADA 2 — guardrail rígido: ABORTA o envio se o lead estiver na blacklist AGORA
        # (opt-out dado entre a criação da campanha e este momento). Marca o job e não envia.
        block_reason = _blacklist_guardrail(lead)
        if block_reason:
            logger.warning(
                "[BROADCAST][BLACKLIST] lead %s (%s) na blacklist — disparo ABORTADO (%s)",
                lead.get("id"), lead.get("phone"), block_reason,
            )
            mark_broadcast_lead_failed(bl["id"], block_reason)
            increment_broadcast_failed(broadcast_id)
            continue

        # CAMADA 2.1 — higiene de lista fria (auditoria 08/07): cliente ativo/contato
        # humano recente não recebe template de "atualização de cadastro" (caso Nayara:
        # compradora de maio levou o template frio 3x em 13 dias).
        hot_reason = _hot_lead_guardrail(lead, broadcast_intent)
        if hot_reason:
            logger.warning(
                "[BROADCAST][HOT] lead %s (%s) — envio pulado (%s)",
                lead.get("id"), lead.get("phone"), hot_reason,
            )
            mark_broadcast_lead_failed(bl["id"], hot_reason)
            increment_broadcast_failed(broadcast_id)
            continue

        # CAMADA 2.2 — dedup lead+template na janela (caso Daniel: re-blast idêntico
        # em 4 dias terminou em "Parar mensagens").
        dedup_reason = _template_dedup_guardrail(lead.get("id"), broadcast.get("template_name"))
        if dedup_reason:
            logger.warning(
                "[BROADCAST][DEDUP] lead %s (%s) — envio pulado (%s)",
                lead.get("id"), lead.get("phone"), dedup_reason,
            )
            mark_broadcast_lead_failed(bl["id"], dedup_reason)
            increment_broadcast_failed(broadcast_id)
            continue

        try:
            channel_id = broadcast.get("channel_id")
            if not channel_id:
                logger.warning(
                    f"[BROADCAST] broadcast {broadcast_id} has no channel_id, skipping lead {lead['phone']}"
                )
                mark_broadcast_lead_failed(bl["id"], "broadcast has no channel_id")
                increment_broadcast_failed(broadcast_id)
                continue

            channel = get_channel_by_id(channel_id)
            if not channel:
                logger.error(f"[BROADCAST] Channel {channel_id} not found, skipping lead {lead['phone']}")
                mark_broadcast_lead_failed(bl["id"], f"channel {channel_id} not found")
                increment_broadcast_failed(broadcast_id)
                continue
            provider = get_provider(channel)
            components = _build_template_components(
                broadcast.get("template_variables") or {},
                lead,
            )
            # Endereço ENTREGÁVEL do DISPARO FRIO. Modo estrito: só confia no wa_id se ele
            # tiver procedência (from real de inbound / captura pós-envio). Lead frio sem
            # histórico → phone de 13 dígitos (E.164 com o 9), a forma canônica que a Meta
            # espera. Evita o descarte silencioso de um wa_id de 12 dígitos poluído.
            send_target = resolve_send_target(
                lead, fallback=lead["phone"], require_inbound_provenance=True
            )
            logger.info(
                "[BROADCAST] sending template '%s' (%s) to %s — components: %s",
                broadcast["template_name"],
                broadcast.get("template_language_code", "pt_BR"),
                send_target,
                components,
            )
            send_response = await provider.send_template(
                to=send_target,
                template_name=broadcast["template_name"],
                components=components,
                language_code=broadcast.get("template_language_code", "pt_BR"),
            )
            # Save wamid BEFORE marking as sent so the crash-recovery window can detect
            # that the message already reached Meta and avoid a duplicate send.
            wamid = None
            try:
                wamid = (send_response.get("messages") or [{}])[0].get("id")
                if wamid:
                    save_broadcast_lead_wamid(bl["id"], wamid)
            except Exception as wamid_err:
                logger.warning("[BROADCAST] Could not save wamid for lead %s: %s", lead["phone"], wamid_err)
            # NB: NÃO carimbamos procedência a partir da resposta SÍNCRONA do envio. A Meta
            # devolve contacts[0].wa_id (e HTTP 200 "accepted") mesmo para endereços que ela
            # NÃO entrega — foi o que recriou a poluição do wa_id. A procedência (wa_id_confirmed_at)
            # passa a vir só de prova ASSÍNCRONA de tráfego real: webhook delivered/read ou inbound
            # (ver _handle_delivery_status e o captura de wa_id do inbound em meta_router).
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Registra observação analítica de disparo no card de CRM (fail-soft).
            record_dispatch_note(lead["id"], broadcast["template_name"])

            # Fire post_broadcast automation trigger (fire-and-forget)
            try:
                from app.automation.triggers import fire_trigger as _fire_trigger
                asyncio.create_task(_fire_trigger("post_broadcast", str(lead["id"]), {
                    "broadcast_id": str(broadcast_id),
                    "replied_only": False,
                }))
            except Exception as trig_err:
                logger.warning("[BROADCAST] post_broadcast trigger error: %s", trig_err)

            # Move lead's deal to configured Kanban stage if set
            if move_to_stage_id and target_pipeline_id:
                try:
                    # Update ALL deals for this lead in the pipeline at once.
                    # Using limit(1) on the previous SELECT+UPDATE left older deals in
                    # the original stage, causing leads to reappear in stage filters.
                    update_result = (
                        sb.table("deals")
                        .update({
                            "stage_id": move_to_stage_id,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })
                        .eq("lead_id", lead["id"])
                        .eq("pipeline_id", target_pipeline_id)
                        .select("id")
                        .execute()
                    )
                    if not update_result.data:
                        # No deal found in this pipeline — create one so the lead is tracked
                        title = (lead.get("name") or lead.get("phone") or "Lead") + " - Oportunidade"
                        sb.table("deals").insert({
                            "lead_id": lead["id"],
                            "title": title,
                            "stage": "novo",
                            "pipeline_id": target_pipeline_id,
                            "stage_id": move_to_stage_id,
                        }).execute()
                    logger.info(
                        "[BROADCAST] Moved/created deal for lead %s to pipeline %s stage %s (deals_updated=%d)",
                        lead["id"], target_pipeline_id, move_to_stage_id, len(update_result.data),
                    )
                    # Track the move timestamp on the broadcast_lead row
                    try:
                        sb.table("broadcast_leads").update({
                            "deal_moved_at": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", bl["id"]).execute()
                    except Exception as track_err:
                        logger.debug("[BROADCAST] deal_moved_at not tracked (run migration): %s", track_err)
                except Exception as move_err:
                    logger.warning(
                        "[BROADCAST] Failed to move deal for lead %s: %s",
                        lead["id"], move_err,
                    )

            # Always record conversation and persist outbound message
            conversation = None
            try:
                logger.info(f"[DEBUG-BROADCAST] step=get_or_create_conversation lead_id={lead['id']} channel_id={channel_id}")
                conversation = get_or_create_conversation(lead["id"], channel_id)
                logger.info(f"[DEBUG-BROADCAST] got conversation id={conversation.get('id') if conversation else None}")
                conv_updates = _build_conv_updates(broadcast)
                logger.info(f"[DEBUG-BROADCAST] step=update_conversation id={conversation['id']} updates={conv_updates}")
                update_conversation(conversation["id"], **conv_updates)
                logger.info(f"[DEBUG-BROADCAST] update_conversation OK")
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not update conversation for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            # Update ai_enabled on the lead regardless of whether conversation update succeeded.
            # This is the gate that controls whether Valeria responds when the lead replies.
            try:
                lead_updates = _build_lead_updates(broadcast, channel, lead, campaign_segment)
                logger.info(f"[DEBUG-BROADCAST] step=update_lead updates={lead_updates} lead_id={lead['id']}")
                update_lead(lead["id"], **lead_updates)
                logger.info(f"[DEBUG-BROADCAST] update_lead OK")
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not update lead ai_enabled for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            try:
                if conversation:
                    logger.info(f"[DEBUG-BROADCAST] step=save_message conv_id={conversation['id']} lead_id={lead['id']}")
                    rendered_content = await _render_template_body(
                        broadcast["template_name"],
                        broadcast.get("template_variables") or {},
                        lead,
                        channel,
                    )
                    saved = save_message(
                        conversation["id"],
                        lead["id"],
                        "assistant",
                        rendered_content,
                        sent_by="broadcast",
                        wamid=wamid,
                        metadata=dispatch_metadata(broadcast["template_name"], broadcast_prompt_key),
                    )
                    logger.info(f"[DEBUG-BROADCAST] save_message OK returned={saved}")
                else:
                    logger.error(
                        f"[BROADCAST] Skipping save_message for {lead['phone']}: no conversation"
                    )
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not save message for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            # Enroll in campaign if configured
            if broadcast.get("campaign_id"):
                try:
                    from app.campaigns.service import (
                        get_campaign, list_nodes, create_enrollment as create_campaign_enrollment,
                        is_already_enrolled,
                    )
                    campaign = get_campaign(broadcast["campaign_id"])
                    if campaign and campaign["status"] == "active":
                        nodes = list_nodes(campaign["id"])
                        trigger = next((n for n in nodes if n["type"] == "trigger"), None)
                        if trigger and trigger.get("next_node_id") and not is_already_enrolled(campaign["id"], lead["id"]):
                            create_campaign_enrollment(
                                campaign_id=campaign["id"],
                                lead_id=lead["id"],
                                current_node_id=trigger["next_node_id"],
                                next_execute_at=datetime.now(timezone.utc),
                            )
                except Exception as ce:
                    logger.warning("[CAMPAIGNS] Could not enroll lead %s from broadcast: %s", lead.get("phone", lead["id"]), ce)

            logger.info(f"Template sent to {lead['phone']}")

        except httpx.HTTPStatusError as http_err:
            meta_err: dict = {}
            try:
                meta_err = http_err.response.json().get("error", {})
                detail = meta_err.get("message", str(http_err))
                code = meta_err.get("code", "")
                error_msg = f"Meta {http_err.response.status_code}: {detail}"
                if code:
                    error_msg += f" (código {code})"
            except Exception:
                error_msg = str(http_err)
            logger.error(f"[BROADCAST] Meta API error para {lead['phone']}: {error_msg}")
            mark_broadcast_lead_failed(bl["id"], error_msg)
            increment_broadcast_failed(broadcast_id)
            # Billing error detected in real-time: pause broadcast immediately so
            # remaining leads are not attempted (they would all fail the same way).
            if meta_err.get("code") == _BILLING_ERROR_CODE:
                logger.critical(
                    "[BROADCAST] Billing error %d — pausando broadcast %s imediatamente",
                    _BILLING_ERROR_CODE, broadcast_id,
                )
                sb.table("broadcasts").update({"status": "paused"}).eq("id", broadcast_id).execute()
                try:
                    from app.alerts.service import fire_billing_alert
                    asyncio.create_task(fire_billing_alert([meta_err]))
                except Exception:
                    pass
                return
        except httpx.TransportError as transport_err:
            # Queda TRANSITÓRIA de conexão (GOAWAY/RemoteProtocolError/ConnectError) que
            # esgotou os retries HTTP do _request_with_retry. NÃO é uma rejeição da Meta —
            # o número provavelmente está OK, a rede é que caiu. Requeue p/ 'pending' (o
            # próximo tick retenta) em vez de queimar o lead como falha permanente. Não
            # incrementa o contador de falhas. Paridade com o retry de GOAWAY do processor.
            logger.warning(
                "[BROADCAST] Erro transitório de conexão p/ %s: %s — requeue (não é falha permanente)",
                lead["phone"], transport_err,
            )
            requeue_broadcast_lead(bl["id"])
        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            mark_broadcast_lead_failed(bl["id"], str(e))
            increment_broadcast_failed(broadcast_id)

        interval = random.randint(
            broadcast.get("send_interval_min", 3),
            broadcast.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)
