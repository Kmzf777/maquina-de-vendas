import logging
import re
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.campaigns.service import (
    get_campaigns_with_trigger_type,
    is_already_enrolled,
    create_enrollment,
)
from app.automation import engine as _engine
from app.campaigns.conversions import fire_conversion_for_deal_stage
from app.leads.reposicao import ensure_reposicao_deal, deal_is_won
# Direto da origem (app.leads.service). app.broadcast.worker so re-exporta, e
# importa-lo aqui puxaria a cadeia inteira do broadcast por uma funcao de uma linha.
from app.leads.service import is_lead_blacklisted
# A marca `metadata.wrong_number_at` nasce em `registrar_numero_errado` e e REMOVIDA
# por `broadcast.worker.process_wrong_number_deadends` quando o dono real responde.
# Reusar a funcao do follow_up (em vez de reimplementar o `metadata.get(...)` aqui)
# mantem a esteira acoplada a esse ciclo de vida.
from app.follow_up.service import lead_marked_wrong_number
# Motor de follow-up do vendedor Joao (spec 2026-09-18). O AGENDADOR vive em
# follow_up/service.py, junto do resto do motor de follow-up; este modulo so o LIGA no
# tick que ja existe — e liga a resposta do lead no gancho de inbound que ja existe.
# Ver o cabecalho da secao "AGENDADOR DAS CADENCIAS DO JOAO" naquele arquivo.
from app.follow_up.service import agendar_cadencias_joao, processar_resposta_joao

logger = logging.getLogger(__name__)


def _keyword_hit(body: str, keywords: list[str]) -> bool:
    """Word-boundary keyword match — prevents false positives from substrings.

    "sim" in "assim" would match with a plain `in` check; this uses (?<!\\w)/(?!\\w)
    anchors so only whole-word (or punctuation-separated) occurrences trigger.
    """
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", body) for k in keywords if k)


def _get_env_tag() -> str:
    try:
        from app.config import settings
        return "dev" if getattr(settings, "is_dev_env", False) else "production"
    except Exception:
        return "production"


def _apply_audience(query, audience: str | None):
    """Aplica o filtro de ai_enabled correspondente ao publico da campanha.

    Espelha engine._audience_allows no lado da CONSULTA. Valor ausente/desconhecido
    cai em 'ia' — o comportamento historico — nunca em 'ambos'.
    """
    modo = audience if audience in ("ia", "humano", "ambos") else "ia"
    if modo == "ambos":
        return query
    return query.eq("ai_enabled", modo == "ia")


def _lead_hard_stop_reason(lead_id: str) -> str | None:
    """Motivo de PARADA DEFINITIVA do lead, ou None se a esteira pode toca-lo.

    Cobre as duas marcas de `metadata` que `follow_up/scheduler.py::_lead_stop_reason`
    trata como parada — as mesmas que fazem o motor de follow-up cancelar um job:
    `wrong_number_at` e `blacklisted_at`.

    NAO reusa `_lead_stop_reason` inteira de proposito: ela tambem para em
    `ai_enabled is False`, que e EXATAMENTE a populacao pos-handoff para a qual as
    esteiras existem (`audience='humano'`). Reusa-la aqui zeraria as quatro esteiras.

    Numero errado e o pior caso possivel para este gatilho: o card fica aberto, o lead
    esta em silencio por definicao e tem `ai_enabled=False` — o candidato perfeito. Cada
    toque iria para um desconhecido, que e quem mais tende a apertar "Bloquear".

    Fail-open em erro de consulta, espelhando `is_lead_blacklisted`: a checagem que
    falha nao bloqueia o tick. A exclusao dura ja acontece na RPC (a mesma condicao
    esta no WHERE de `get_deals_stage_stagnant`); esta aqui e defesa em profundidade.
    """
    try:
        rows = (
            get_supabase().table("leads").select("metadata")
            .eq("id", lead_id).limit(1).execute().data
        )
    except Exception as exc:
        logger.warning("[AUTOMATION] leitura de metadata do lead %s falhou: %s", lead_id, exc)
        return None
    lead = rows[0] if isinstance(rows, list) and rows else None
    if lead_marked_wrong_number(lead):
        return "wrong_number"
    meta = (lead or {}).get("metadata") or {}
    if isinstance(meta, dict) and meta.get("blacklisted_at"):
        return "blacklisted"
    return None


def _maybe_fire_stage_conversion(lead_id: str, data: dict) -> None:
    """Se a etapa que o deal entrou estiver marcada com conversion_event, dispara a conversão.

    Delega para fire_conversion_for_deal_stage (campaigns/conversions.py) — helper
    compartilhado também chamado por engine._execute_action em move_deal_stage/mark_deal_won.
    """
    deal_id = data.get("deal_id")
    if not deal_id:
        return
    fire_conversion_for_deal_stage(lead_id, deal_id)


async def fire_trigger(event_type: str, lead_id: str, data: dict | None = None) -> None:
    """Event-driven: enroll lead in all active campaigns with matching trigger."""
    try:
        data = data or {}
        now = datetime.now(timezone.utc)

        if event_type == "deal_stage_enter":
            _maybe_fire_stage_conversion(lead_id, data)
            # Ciclo de reposição: se o deal entrou em 'fechado_ganho', garante nova oportunidade.
            # deal_id repassado: o destino do card de reposição depende do funil de
            # ORIGEM deste deal (ver reposicao.reposicao_pipeline_para).
            if deal_is_won(data.get("deal_id")):
                ensure_reposicao_deal(lead_id, deal_id=data.get("deal_id"))

        if event_type == "sale_created":
            # Registrar venda move o deal p/ fechado_ganho sem emitir deal_stage_enter → hook aqui.
            ensure_reposicao_deal(lead_id, deal_id=data.get("deal_id"))

        if event_type == "message_received":
            # RESPOSTA DO LEAD ÀS CADÊNCIAS DO JOÃO (ata 41:40): "ainda tenho estoque"
            # adia 60 dias sem recomeçar; o botão de saída vira opt-out real.
            #
            # O GANCHO É REUSADO, não inventado. `buffer/processor.py` dispara este
            # `fire_trigger('message_received')` em TODO inbound, com o texto do lead em
            # `data['body']` — e o faz ANTES do gate de canal humano, que é exatamente
            # onde o público do João fica (mode='human', ai_enabled=False). É o mesmo
            # ponto do fluxo em que `handle_campaign_reply` recebe a resposta das
            # cadências do builder, duas linhas acima na mesma função.
            #
            # `processar_resposta_joao` sai em None antes de qualquer consulta quando o
            # texto não é um dos dois rótulos — o caminho quente do inbound não paga
            # nada por isto.
            try:
                processar_resposta_joao(lead_id, data.get("body"))
            except Exception as exc:
                logger.error(
                    "[JOAO_CADENCIA] resposta do lead %s não processada: %s", lead_id, exc)

            message_body = (data.get("body") or "").lower()
            for tn in get_campaigns_with_trigger_type("keyword_received"):
                cfg = tn.get("config") or {}
                keywords = [k.lower() for k in (cfg.get("keywords") or []) if k]
                if not keywords or not _keyword_hit(message_body, keywords):
                    continue
                if is_already_enrolled(tn["campaign_id"], lead_id) or not tn.get("next_node_id"):
                    continue
                if _engine._conversation_followup_disabled(lead_id, tn.get("channel_id")):
                    logger.info("[AUTOMATION] keyword_received: conversation finalized — skip enrollment for lead %s", lead_id)
                    continue
                try:
                    create_enrollment(
                        campaign_id=tn["campaign_id"],
                        lead_id=lead_id,
                        current_node_id=tn["next_node_id"],
                        next_execute_at=now,
                    )
                    logger.info("[AUTOMATION] Enrolled %s via keyword_received", lead_id)
                except Exception as enroll_err:
                    logger.warning("[AUTOMATION] Failed to enroll %s via keyword_received: %s", lead_id, enroll_err)
            return

        for trigger_node in get_campaigns_with_trigger_type(event_type):
            if not _passes_filter(event_type, trigger_node.get("config") or {}, data):
                continue
            if is_already_enrolled(trigger_node["campaign_id"], lead_id):
                continue
            if not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(
                    campaign_id=trigger_node["campaign_id"],
                    lead_id=lead_id,
                    current_node_id=trigger_node["next_node_id"],
                    next_execute_at=now,
                    deal_id=data.get("deal_id"),
                )
                logger.info("[AUTOMATION] Enrolled %s via %s", lead_id, event_type)
            except Exception as enroll_err:
                logger.warning("[AUTOMATION] Failed to enroll %s via %s: %s", lead_id, event_type, enroll_err)
    except Exception as e:
        logger.error("[AUTOMATION] fire_trigger(%s, lead=%s) failed: %s", event_type, lead_id, e)


def _passes_filter(event_type: str, cfg: dict, data: dict) -> bool:
    if event_type in ("stage_enter", "deal_stage_enter"):
        stage_filter = cfg.get("stage_filter")
        return not stage_filter or data.get("stage") == stage_filter

    if event_type == "sale_created":
        if cfg.get("min_value") and float(data.get("value", 0)) < cfg["min_value"]:
            return False
        if cfg.get("product_filter"):
            if cfg["product_filter"].lower() not in (data.get("product") or "").lower():
                return False
        return True

    if event_type == "tag_added":
        tag_filter = cfg.get("tag_name")
        return not tag_filter or data.get("tag_name") == tag_filter

    return True  # deal_closed_lost, post_broadcast — no additional filter


async def check_polling_triggers(now: datetime | None = None) -> None:
    """Polling: detect inactivity-based conditions and enroll leads."""
    now = now or datetime.now(timezone.utc)
    sb = get_supabase()
    env_tag = _get_env_tag()

    # ── cadências do João (spec 2026-09-18) ───────────────────────────────────
    # O motor do vendedor NÃO é um segundo motor: os jobs nascem em `follow_up_jobs` e o
    # scheduler que já existe os despacha. O que falta é quem os CRIA — o agendador, que
    # vive em `follow_up/service.py` e reusa a mesma RPC `get_deals_stage_stagnant` dos
    # gatilhos abaixo. Fica aqui porque este é o tick de polling que já varre funil.
    #
    # FAIL-SOFT, e no topo: uma falha nas cadências do João não pode derrubar as
    # esteiras que já rodam em produção, e o inverso também não.
    try:
        agendar_cadencias_joao(now)
    except Exception as exc:
        logger.error("[JOAO_CADENCIA] varredura falhou: %s", exc, exc_info=True)

    # ── no_message ────────────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_message"):
        cfg = tn.get("config") or {}
        days, stage_filter = cfg.get("days", 30), cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("id, phone").lte("last_msg_at", cutoff)
        q = _apply_audience(q, tn.get("audience"))
        if stage_filter:
            q = q.eq("stage", stage_filter)
        for lead in q.limit(20).execute().data:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── stage_stagnation ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("stage_stagnation"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("id, phone")
        q = _apply_audience(q, tn.get("audience"))
        leads = (
            q.eq("stage", stage)
            .not_.is_("entered_stage_at", "null").lte("entered_stage_at", cutoff)
            .limit(20).execute().data
        )
        for lead in leads:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── repurchase_window ─────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("repurchase_window"):
        cfg = tn.get("config") or {}
        days = cfg.get("days", 30)
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_for_repurchase", {
            "cutoff_date": cutoff, "p_env_tag": env_tag, "p_audience": tn.get("audience") or "ia",
        }).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── no_sale_in_stage ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_sale_in_stage"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_no_sale_in_stage", {
            "p_stage": stage, "cutoff_date": cutoff, "p_env_tag": env_tag,
            "p_audience": tn.get("audience") or "ia",
        }).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── deal_stage_stagnation ─────────────────────────────────────────────────
    # Card parado numa COLUNA DO KANBAN (deals.stage_id), nao no segmento do lead.
    # E o gatilho das tres esteiras do vendedor; a RPC resolve etapa, silencio,
    # falante e publico numa consulta so (ver 20260904_esteiras_vendedor.sql).
    for tn in get_campaigns_with_trigger_type("deal_stage_stagnation"):
        cfg = tn.get("config") or {}
        if not tn.get("next_node_id"):
            continue
        # `or None` nos tres primeiros: o <select> do builder usa value="" para
        # "— qualquer —", e "" mandado num parametro uuid da RPC e erro de sintaxe
        # no Postgres, nao "sem filtro". Sem isso, gatilho salvo sem etapa explicita
        # morreria todo tick no except abaixo.
        # Gatilho sem etapa NENHUMA (stage_id e stage_key nulos) nao varre mais a base:
        # a RPC devolve conjunto vazio nesse caso — fail-closed no lugar mais profundo,
        # que vale tambem para gatilho montado a mao na aba Cadencias.
        args = {
            "p_stage_id": cfg.get("stage_id") or None,
            "p_stage_key": cfg.get("stage_key") or None,
            "p_pipeline_id": cfg.get("pipeline_id") or None,
            "p_channel_id": tn.get("channel_id"),
            "p_stage_days": int(cfg.get("stage_days") or 0),
            "p_silence_days": int(cfg.get("silence_days") or 0),
            "p_last_speaker": cfg.get("last_speaker") or "qualquer",
            "p_audience": tn.get("audience") or "ia",
            "p_limit": int(cfg.get("limit") or 20),
            # Sem isto a esteira NUNCA PARA. `is_already_enrolled` (abaixo) so conta
            # enrollment 'active'/'paused'; ao chegar no no `end` ele vira 'completed'
            # e nada impede a reinscricao do MESMO card no tick seguinte — em
            # `novo_reengajamento` isso e um template a cada 3 dias, para sempre. Com o
            # campaign_id a RPC exclui quem ja passou por esta campanha dentro do
            # cooldown (default 90 dias, ver 20260904_esteiras_vendedor.sql).
            "p_campaign_id": tn["campaign_id"],
        }
        try:
            linhas = sb.rpc("get_deals_stage_stagnant", args).execute().data or []
        except Exception as exc:
            logger.error("[AUTOMATION] deal_stage_stagnation: RPC falhou: %s", exc)
            continue
        for linha in linhas:
            lead_id = linha["lead_id"]
            if is_already_enrolled(tn["campaign_id"], lead_id):
                continue
            if _engine._conversation_followup_disabled(lead_id, tn.get("channel_id")):
                continue
            # Guarda que os gatilhos antigos nao tem: a esteira de reposicao varre a
            # base inteira e e exatamente onde esta quem ja pediu para nao receber mais.
            if is_lead_blacklisted(lead_id):
                logger.info("[AUTOMATION] deal_stage_stagnation: lead %s na blacklist — skip", lead_id)
                continue
            # Numero errado / blacklisted_at: o motor de follow-up para nos dois e o
            # gatilho nao parava em nenhum. Ver _lead_hard_stop_reason.
            motivo = _lead_hard_stop_reason(lead_id)
            if motivo:
                logger.info("[AUTOMATION] deal_stage_stagnation: lead %s com %s — skip", lead_id, motivo)
                continue
            try:
                create_enrollment(
                    campaign_id=tn["campaign_id"],
                    lead_id=lead_id,
                    current_node_id=tn["next_node_id"],
                    next_execute_at=now,
                    deal_id=linha.get("deal_id"),
                    metadata={"guard": {
                        "deal_id": linha.get("deal_id"),
                        "stage_id": linha.get("stage_id"),
                        "stage_key": cfg.get("stage_key") or None,
                    }},
                )
                logger.info("[AUTOMATION] Enrolled %s via deal_stage_stagnation", lead_id)
            except Exception as exc:
                logger.warning("[AUTOMATION] deal_stage_stagnation enroll falhou p/ %s: %s", lead_id, exc)


def _safe_enroll(trigger_node: dict, lead_id: str, now: datetime) -> None:
    if _engine._conversation_followup_disabled(lead_id, trigger_node.get("channel_id")):
        logger.info("[AUTOMATION] polling: conversation finalized — skip enrollment for lead %s", lead_id)
        return
    try:
        create_enrollment(trigger_node["campaign_id"], lead_id, trigger_node["next_node_id"], now)
        logger.info("[AUTOMATION] polling enrolled %s via %s", lead_id, trigger_node.get("type"))
    except Exception as e:
        logger.warning("[AUTOMATION] polling enroll failed: %s", e)


