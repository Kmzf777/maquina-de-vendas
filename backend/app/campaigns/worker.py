"""Peças vivas do fluxo de campanhas.

O loop próprio deste módulo (check_campaign_triggers / process_campaign_enrollments)
foi substituído pelo automation engine (app/automation/engine.py) e removido em
09/07/2026 (~200 linhas mortas). Permanecem apenas as funções consumidas por
outros módulos:

- `_execute_send_node`  → automation/engine.py (nó `send` das cadências)
- `handle_campaign_reply` → buffer/processor.py (inbound pausa/cancela enrollment)
- `decide_failure_update` / `_is_permanent_error` → classificador puro de erro Meta
  (permanente vs transitório) com suíte própria (test_campaigns_worker_retry.py)
"""
import logging
from datetime import datetime

from app.campaigns.service import (
    cancel_enrollment,
    pause_enrollment,
)
from app.automation.retry import calculate_next_retry

logger = logging.getLogger(__name__)

# Status HTTP da Meta que não adianta retentar (template/locale/param errados):
# o disparo nunca vai ser aceito — cancelar a enrollment em vez de re-armar.
_PERMANENT_STATUS = {400, 403, 404}


def _is_permanent_error(exc: Exception) -> bool:
    """True para rejeições da Meta que não mudam com retry (4xx de template/param).

    Cobre dois formatos: httpx.HTTPStatusError (raise_for_status em 4xx) e o
    RuntimeError que send_template/send_text levantam quando a Meta devolve HTTP 200
    com erro embutido ('... rejected (missing messages ...)').
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _PERMANENT_STATUS:
        return True
    if isinstance(exc, RuntimeError) and "rejected" in str(exc):
        return True
    return False


def decide_failure_update(exc: Exception, retry_count: int, now: datetime) -> dict:
    """Pure: kwargs para update_enrollment que SEMPRE tiram a enrollment do estado
    imediatamente-due — raiz do loop que inflou meta_webhook_logs.

    - Erro permanente (4xx / rejeição embutida): status='cancelled'.
    - Erro transitório: backoff via calculate_next_retry (1h/4h/24h, teto 3);
      ao estourar o teto, cancela.
    """
    err = str(exc)[:500]
    if _is_permanent_error(exc):
        return {"status": "cancelled", "last_error": err}
    next_at, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        return {"status": "cancelled", "last_error": err}
    iso = next_at.isoformat()
    return {
        "retry_count": new_count,
        "next_retry_at": iso,
        "next_execute_at": iso,
        "last_error": err,
    }


async def _execute_send_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.whatsapp.registry import get_provider
    from app.channels.service import get_channel_for_lead
    from app.broadcast.worker import (
        _build_template_components, _render_template_body, _broadcast_ai_enabled,
    )
    from app.conversations.service import get_or_create_conversation, update_conversation, save_message
    from app.leads.service import update_lead, record_dispatch_note

    cfg = node["config"]
    template_name = cfg["template_name"]
    template_variables = cfg.get("template_variables", {})
    channel_id = cfg.get("channel_id")

    channel = None
    if channel_id:
        from app.channels.service import get_channel_by_id
        channel = get_channel_by_id(channel_id)
    if not channel:
        channel = get_channel_for_lead(enrollment["lead_id"])
    if not channel:
        logger.warning("[CAMPAIGNS] No channel for lead %s, skipping send", lead["phone"])
        return

    provider = get_provider(channel)
    components = _build_template_components(template_variables, lead)
    send_resp = await provider.send_template(
        to=lead["phone"],
        template_name=template_name,
        components=components,
        language_code=cfg.get("template_language", "pt_BR"),
    )

    wamid = None
    try:
        wamid = (send_resp.get("messages") or [{}])[0].get("id")
    except Exception:
        pass

    # Registra observação analítica de disparo no card de CRM (fail-soft).
    record_dispatch_note(enrollment["lead_id"], template_name)

    # Persist conversation + message
    try:
        conv = get_or_create_conversation(enrollment["lead_id"], channel["id"])
        update_conversation(conv["id"], status="template_sent")
        rendered = await _render_template_body(template_name, template_variables, lead, channel)
        save_message(conv["id"], enrollment["lead_id"], "assistant", rendered, sent_by="campaign", wamid=wamid)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not persist conversation for %s: %s", lead["phone"], e)

    # Update ai_enabled
    try:
        agent_profile_id = cfg.get("agent_profile_id")
        fake_broadcast = {"agent_profile_id": agent_profile_id}
        ai_enabled = _broadcast_ai_enabled(fake_broadcast, channel)
        update_lead(enrollment["lead_id"], ai_enabled=ai_enabled)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not update ai_enabled for %s: %s", lead["phone"], e)

    logger.info("[CAMPAIGNS] Sent template '%s' to %s", template_name, lead["phone"])


def handle_campaign_reply(lead_id: str) -> None:
    """Called by webhook when a lead sends a message. Pauses (or cancels) the
    active enrollment regardless of which node it is currently parked on.

    Previously this only acted when the current node was `send`; enrollments
    sitting in `wait` / `condition` / `action` ignored the reply and would
    advance to the next `send`, mailing the lead despite engagement. We now
    treat any inbound message as a signal to pause; the seller can resume
    manually if needed. on_reply='cancel' is still honored on `send` nodes.
    """
    from app.campaigns.service import get_active_enrollment_for_lead
    enrollment = get_active_enrollment_for_lead(lead_id)
    if not enrollment:
        return
    node = enrollment.get("campaign_nodes") or {}
    on_reply = (node.get("config") or {}).get("on_reply", "pause")
    if node.get("type") == "send" and on_reply == "cancel":
        cancel_enrollment(enrollment["id"])
        logger.info(
            "[CAMPAIGNS] Cancelled enrollment %s — lead replied (on_reply=cancel)",
            enrollment["id"],
        )
        return
    pause_enrollment(enrollment["id"])
    logger.info(
        "[CAMPAIGNS] Paused enrollment %s — lead replied (node_type=%s)",
        enrollment["id"], node.get("type"),
    )
