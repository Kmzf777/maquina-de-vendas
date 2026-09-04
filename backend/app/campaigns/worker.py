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

logger = logging.getLogger(__name__)

# Back-compat re-exports: decide_failure_update + _is_permanent_error were moved
# to app.automation.retry in Task 4. Re-exported here so existing callers/tests
# that import from campaigns.worker continue to work without modification.
from app.automation.retry import decide_failure_update, _is_permanent_error  # noqa: F401


async def _execute_send_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> str | None:
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
        return None

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
    return wamid


def _trigger_on_reply(campaign_id: str | None) -> str | None:
    """`on_reply` do nó de GATILHO — a política de resposta da cadeia INTEIRA.

    O nó de envio descreve um toque; o gatilho descreve a esteira. A distinção importa
    porque um enrollment passa a maior parte da vida parado num nó `wait` — e é ali que
    a maioria das respostas chega. Sem esta consulta, `on_reply='cancel'` configurado
    nos envios nunca era alcançado: o enrollment ia para `paused`, estado que
    `is_already_enrolled` conta como ativo e que ninguém retoma, deixando o lead
    inelegível para reentrar na esteira para sempre.

    FAIL-SAFE: campanha sem gatilho, sem o campo, ou erro de leitura → None, e o
    chamador pausa. Pausar por engano é recuperável; cancelar por engano perde a esteira.
    """
    if not campaign_id:
        return None
    try:
        from app.campaigns.service import list_nodes
        for n in list_nodes(campaign_id) or []:
            if n.get("type") == "trigger":
                return (n.get("config") or {}).get("on_reply") or None
    except Exception as exc:
        logger.warning(
            "[CAMPAIGNS] on_reply do gatilho: falha ao ler campanha %s: %s — pausando",
            campaign_id, exc,
        )
    return None


def handle_campaign_reply(lead_id: str) -> None:
    """Called by webhook when a lead sends a message. Pauses (or cancels) the
    active enrollment regardless of which node it is currently parked on.

    Previously this only acted when the current node was `send`; enrollments
    sitting in `wait` / `condition` / `action` ignored the reply and would
    advance to the next `send`, mailing the lead despite engagement. We now
    treat any inbound message as a signal to pause; the seller can resume
    manually if needed.

    Precedência de `on_reply`: o nó atual, quando define o seu, vence — inclusive para
    forçar `pause` contra um gatilho que pede `cancel`. Sem valor no nó, vale o do nó de
    gatilho (a política da esteira inteira). `cancel` vindo do NÓ segue restrito a nós
    `send`, como sempre foi: `system_cadence` grava `on_reply='cancel'` em nós
    `send_text` que hoje pausam, e honrá-lo agora mudaria campanha existente.
    """
    from app.campaigns.service import get_active_enrollment_for_lead
    enrollment = get_active_enrollment_for_lead(lead_id)
    if not enrollment:
        return
    node = enrollment.get("campaign_nodes") or {}
    node_on_reply = (node.get("config") or {}).get("on_reply") or None
    if node_on_reply is not None:
        cancelar = node_on_reply == "cancel" and node.get("type") == "send"
        origem = "nó"
    else:
        cancelar = _trigger_on_reply(enrollment.get("campaign_id")) == "cancel"
        origem = "gatilho"
    if cancelar:
        cancel_enrollment(enrollment["id"])
        logger.info(
            "[CAMPAIGNS] Cancelled enrollment %s — lead replied (on_reply=cancel via %s)",
            enrollment["id"], origem,
        )
        return
    pause_enrollment(enrollment["id"])
    logger.info(
        "[CAMPAIGNS] Paused enrollment %s — lead replied (node_type=%s)",
        enrollment["id"], node.get("type"),
    )
