"""Peças vivas do fluxo de campanhas.

O loop próprio deste módulo (check_campaign_triggers / process_campaign_enrollments)
foi substituído pelo automation engine (app/automation/engine.py) e removido em
09/07/2026 (~200 linhas mortas). Permanecem apenas as funções consumidas por
outros módulos:

- `_execute_send_node`  → automation/engine.py (nó `send` das cadências)
- `handle_campaign_reply` → buffer/processor.py (inbound pausa/cancela enrollments)
- `handle_optout_reply` / `is_optout_reply` → buffer/processor.py (opt-out determinístico
  do botão de saída dos templates, para o público que nunca chega ao LLM)
- `decide_failure_update` / `_is_permanent_error` → classificador puro de erro Meta
  (permanente vs transitório) com suíte própria (test_campaigns_worker_retry.py)
"""
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.campaigns.service import (
    cancel_enrollment,
    pause_enrollment,
    reset_enrollment,
)

logger = logging.getLogger(__name__)

_TZ_BR = timezone(timedelta(hours=-3))

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
    from app.leads.service import update_lead, record_dispatch_note, is_lead_blacklisted

    # CAMADA 2 — guardrail no instante do envio, espelhando `broadcast/worker.py::
    # _blacklist_guardrail`. A camada 1 (filtro de blacklist no gatilho) só protege quem
    # ainda não entrou: um opt-out registrado NO MEIO de uma esteira não cancela
    # enrollment nenhum — nem o do botão, nem a tool `registrar_optout`, nem o
    # POST /api/leads/{id}/optout do operador: os três cancelam follow-ups e movem deals,
    # e nenhum toca `campaign_enrollments`. Sem esta re-checagem, o próximo toque saía
    # para quem tinha acabado de pedir para parar.
    if is_lead_blacklisted(enrollment.get("lead_id")):
        logger.warning(
            "[CAMPAIGNS] envio abortado — lead %s está na blacklist (opt-out / pipeline Blacklist)",
            enrollment.get("lead_id"),
        )
        return None

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


def _trigger_first_node(campaign_id: str | None) -> str | None:
    """`next_node_id` do nó de gatilho — o primeiro nó EXECUTÁVEL da esteira.

    É para ele que `on_reply='reset'` rebobina. Espelha `_trigger_on_reply`: mesma
    consulta (import local de `list_nodes`, para casar com o alvo de patch já usado por
    `test_esteiras_on_reply.py` / `test_esteiras_reply_todos_enrollments_2026_09_04.py`
    — `app.campaigns.service.list_nodes`), mesma doutrina fail-safe (None → o chamador
    pausa em vez de adivinhar).
    """
    if not campaign_id:
        return None
    try:
        from app.campaigns.service import list_nodes
        for n in list_nodes(campaign_id) or []:
            if n.get("type") == "trigger" and n.get("next_node_id"):
                return n["next_node_id"]
    except Exception as exc:
        logger.error("[CAMPAIGNS] falha ao resolver o primeiro nó de %s: %s", campaign_id, exc)
    return None


def handle_campaign_reply(lead_id: str) -> None:
    """Called by webhook when a lead sends a message. Pauses (or cancels) EVERY
    active enrollment of the lead, regardless of which node each one is parked on.

    Previously this only acted when the current node was `send`; enrollments
    sitting in `wait` / `condition` / `action` ignored the reply and would
    advance to the next `send`, mailing the lead despite engagement. We now
    treat any inbound message as a signal to pause; the seller can resume
    manually if needed.

    E age sobre TODOS os enrollments, não sobre um. `is_already_enrolled` é por
    CAMPANHA, então o mesmo lead pode estar em duas esteiras ao mesmo tempo — e é o caso
    normal do desenho: card de recompra em "Já chamado" (esteira de reposição) + card em
    "Proposta Enviada" (esteira de proposta). Tratando só a linha que o banco devolvesse
    primeiro, ou a esteira de proposta mandava o D+8 para quem já respondeu, ou a de
    reposição rodava até o fim e marcava como PERDIDO o card de um lead que engajou.

    Cada enrollment é tratado ISOLADO — erro em um não pode deixar os outros armados.
    """
    from app.campaigns.service import get_active_enrollments_for_lead
    for enrollment in get_active_enrollments_for_lead(lead_id) or []:
        try:
            _apply_reply_policy(enrollment)
        except Exception as exc:
            logger.error(
                "[CAMPAIGNS] falha ao aplicar on_reply no enrollment %s do lead %s: %s",
                enrollment.get("id"), lead_id, exc, exc_info=True,
            )


def _apply_reply_policy(enrollment: dict) -> None:
    """Pausa, cancela ou reseta UM enrollment segundo a sua própria política de `on_reply`.

    Precedência: o nó atual, quando define o seu, vence — inclusive para forçar `pause`
    contra um gatilho que pede `cancel`. Sem valor no nó, vale o do nó de gatilho (a
    política da esteira inteira). `cancel` vindo do NÓ segue restrito a nós `send`, como
    sempre foi: `system_cadence` grava `on_reply='cancel'` em nós `send_text` que hoje
    pausam, e honrá-lo agora mudaria campanha existente.

    `reset` (reunião de 10/09/2026, esteira "Em conversa") rebobina a matrícula para o
    primeiro nó em vez de encerrá-la — ver `service.reset_enrollment` para o porquê de
    ela permanecer `active`.
    """
    node = enrollment.get("campaign_nodes") or {}
    node_on_reply = (node.get("config") or {}).get("on_reply") or None
    if node_on_reply is not None:
        politica = node_on_reply
        origem = "nó"
    else:
        politica = _trigger_on_reply(enrollment.get("campaign_id"))
        origem = "gatilho"

    # `reset` rebobina em vez de encerrar (esteira "Em conversa", reunião de 10/09/2026).
    # Fail-safe: sem primeiro nó resolvido, pausa — pausar por engano é recuperável.
    if politica == "reset":
        primeiro = _trigger_first_node(enrollment.get("campaign_id"))
        if primeiro:
            reset_enrollment(enrollment["id"], primeiro)
            logger.info(
                "[CAMPAIGNS] Reset enrollment %s — lead respondeu (on_reply=reset via %s)",
                enrollment["id"], origem,
            )
            return
        logger.warning(
            "[CAMPAIGNS] on_reply=reset em %s sem primeiro nó resolvível — pausando",
            enrollment["id"],
        )

    # `cancel` vindo do NÓ segue restrito a nós `send`, como sempre foi.
    cancelar = politica == "cancel" and (origem == "gatilho" or node.get("type") == "send")
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


# ─── Opt-out determinístico (sem LLM) ────────────────────────────────────────────
#
# Os templates de esteira e o corpus outbound trazem uma SAÍDA DIGNA como QUICK_REPLY —
# é ela que protege o rating do número. A spec §7 afirma que esse botão "já alimenta a
# blacklist"; era falso para o público das esteiras. `leads.opt_out` só era gravado pela
# tool `registrar_optout`, que SÓ o agente LLM chama, e lead de esteira tem
# `ai_enabled=False` por definição (o handoff desliga a IA), num número de vendedor que
# roda `mode='human'`. Nos dois casos o inbound retorna antes do agente: apertar o botão
# cancelava um enrollment e nada mais — sem `opt_out`, sem pipeline Blacklist, sem
# cancelar follow-up. Somado à reinscrição das esteiras, quem disse "não tenho interesse"
# voltava a receber dias depois.
_OPTOUT_REPLY_LABELS: frozenset[str] = frozenset({
    "nao tenho interesse",  # esteiras do vendedor (scripts/create_esteira_templates.py)
    "parar mensagens",      # corpus outbound da Valéria
})

_RE_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_RE_WS = re.compile(r"\s+")


def _normalize_reply(text: str | None) -> str:
    """minúsculas, sem acento, sem pontuação, espaços colapsados. Função PURA.

    Mesma receita de `follow_up/scheduler.py::_strip_accents` e
    `agent/tools.py::_normalize_for_dedup`; reescrita aqui (4 linhas) para não acoplar o
    caminho quente do inbound ao grafo de imports daqueles módulos.
    """
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return _RE_WS.sub(" ", _RE_PUNCT.sub(" ", t)).strip()


def is_optout_reply(text: str | None) -> bool:
    """True SÓ quando a mensagem INTEIRA é o rótulo do botão de saída.

    IGUALDADE normalizada, nunca substring — e a diferença é a de um lead quente virar
    blacklist permanente: "não tenho interesse em cápsulas, só em grãos" é interesse.
    Por isso não serve nem `in`, nem o `_keyword_hit` de `automation/triggers.py`, que é
    casamento com fronteira de palavra (ainda substring).

    O parser da Meta achata o clique de QUICK_REPLY em texto (`meta_parser.py`: tipo
    `button` e `interactive.button_reply` viram `type='text'` com o rótulo no corpo),
    então botão e digitação são indistinguíveis aqui — a igualdade é o que garante que
    só a frase exata conte.
    """
    return _normalize_reply(text) in _OPTOUT_REPLY_LABELS


def handle_optout_reply(
    lead: dict | None, text: str | None, conversation_id: str | None = None,
) -> bool:
    """Grava a marca de blacklist quando o inbound É a saída de opt-out. True se gravou.

    Escreve os MESMOS campos de `agent/tools.py::registrar_optout` — `leads.opt_out=True`
    + `apply_optout_side_effects` (deals para o pipeline Blacklist + cancelamento dos
    follow-ups pendentes) — para não existirem duas definições de "está na blacklist"
    divergindo. É esse par que `leads/service.py::is_lead_blacklisted` lê.

    NÃO envia mensagem nenhuma: quem pediu para sair não recebe despedida automática
    (e o público daqui está num número humano, onde a IA não fala).

    Marcador próprio no histórico (`[optout_botao]`, não `[registrar_optout]`): o QA
    diário do watchdog conta `[registrar_optout]%` para medir o comportamento do LLM —
    contaminar aquele número com o que o LLM não fez estragaria a métrica.

    Fail-soft em todos os passos: erro aqui não pode derrubar o processamento da mensagem.
    """
    if not is_optout_reply(text):
        return False
    lead = lead or {}
    lead_id = lead.get("id")
    if not lead_id or lead.get("opt_out"):
        return False  # idempotente: quem já está na blacklist não é regravado
    try:
        from app.leads.service import update_lead
        update_lead(lead_id, ai_enabled=False, opt_out=True)
    except Exception as exc:
        logger.error(
            "[OPT-OUT] falha ao gravar opt_out do lead %s: %s", lead_id, exc, exc_info=True,
        )
        return False
    limpo = (text or "").strip()
    try:
        from app.leads.service import (
            append_lead_observation, apply_optout_side_effects, save_message,
        )
        apply_optout_side_effects(lead_id, lead.get("phone") or "", reason="optout_botao")
        _ts = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
        append_lead_observation(
            lead_id,
            f"🚫 [OPT-OUT DEFINITIVO] Registado em {_ts}. "
            f"Motivo: lead escolheu a saída de opt-out do template ({limpo!r}).",
        )
        save_message(
            lead_id, "system",
            f"[optout_botao] lead escolheu a saída de opt-out do template: {limpo!r}",
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.error(
            "[OPT-OUT] efeitos colaterais do opt-out do lead %s falharam (opt_out já gravado): %s",
            lead_id, exc, exc_info=True,
        )
    logger.info(
        "[OPT-OUT] opt_out=True gravado sem LLM para o lead %s — texto=%r", lead_id, limpo,
    )
    return True
