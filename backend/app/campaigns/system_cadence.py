"""Espelho VISUAL do motor de follow-up no builder de Cadências (10/07/2026).

A lógica temporal da Valéria (T1 same-day+jitter, T2 D+1, T3 D+3, T4 D+6h20, nudge
outbound +18h, janela de 24h da Meta → template de reabertura, regra R1) vive em
`follow_up/cadence.py` e era invisível na UI. Este módulo materializa esse fluxo como
uma campanha DE SISTEMA no builder React Flow existente (tabelas campaigns/
campaign_nodes), construída A PARTIR do próprio cadence.py — os `objective_prompt`
reais viram o texto dos nós e as constantes do template de reabertura vêm do
scheduler. Zero drift: `sync_valeria_cadence_campaign()` roda no startup da API
(lifespan) e re-sincroniza a cada deploy, desfazendo inclusive edições manuais.

SEGURANÇA DE EXECUÇÃO: a campanha é um ESPELHO, nunca um executor. Ela nasce e
permanece `status='draft'` (o automation engine só processa campanhas `active` — gates
em get_due_enrollments/_process_one/get_campaigns_with_trigger_type) e o router recusa
activate/enroll/delete para o UUID de sistema (ver campaigns/router.py). A execução
real continua exclusiva do worker de follow-up.
"""
from __future__ import annotations

import logging
import uuid

from app.campaigns.service import _ENV_TAG
from app.db.supabase import get_supabase
from app.follow_up.cadence import CADENCE, OUTBOUND_NUDGE

logger = logging.getLogger(__name__)

# UUID fixo e determinístico da campanha-espelho. O frontend duplica este literal em
# src/lib/system-campaign.ts (com teste fixando o valor) para o banner read-only e o
# bloqueio do toggle de ativação.
VALERIA_CADENCE_CAMPAIGN_ID = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "canastra://system/valeria-followup-cadence")
)

VALERIA_CADENCE_CAMPAIGN_NAME = "Valéria — Follow-up (motor)"
VALERIA_CADENCE_CAMPAIGN_DESCRIPTION = (
    "[SISTEMA] Espelho somente-leitura do motor de follow-up da Valéria "
    "(backend/app/follow_up/cadence.py). Re-sincronizado a cada deploy — edições "
    "manuais são desfeitas. NÃO ativável: a execução real é do worker de follow-up; "
    "ativar esta campanha duplicaria os toques."
)

_JANELA = "janela comercial 9h–16h BRT, seg–sex (fora dela o toque é empurrado)"


def _node_id(key: str) -> str:
    """UUID determinístico por chave estável — permite FKs pré-computadas e sync
    idempotente (o mesmo nó tem o mesmo id em toda execução)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"canastra://system/valeria-followup-cadence/{key}"))


def _touch_text(header: str, objective_prompt: str, footer: str | None = None) -> str:
    parts = [header, "", objective_prompt.strip()]
    if footer:
        parts += ["", footer]
    return "\n".join(parts)


def build_valeria_cadence_graph() -> tuple[dict, list[dict]]:
    """(campanha, nós) do espelho — função PURA, fonte = cadence.py + scheduler.

    Mapa de fidelidade:
    - `on_reply: "cancel"` nos toques livres = resposta do lead cancela/re-arma a
      cadência (comportamento real de schedule_followup).
    - condition `replied_recently days=1` = "janela de 24h da Meta aberta?" — decisiva
      no T2 (o D+1 vence sempre ~24h+ε após a última msg do lead, ver spec Rodada 5).
    - Ramo "no" = template de reabertura com os valores REAIS do scheduler; T3/T4 se
      dobram nele (R1) — por isso o ramo termina em `end` "aguardando reabertura".
    """
    # Import local: evita ciclo (scheduler importa half do app) e mantém a fonte única.
    from app.follow_up.scheduler import _REOPEN_TEMPLATE_LANGUAGE, _REOPEN_TEMPLATE_NAME, _REOPEN_TOPIC

    t1, t2, t3, t4 = CADENCE

    campaign = {
        "id": VALERIA_CADENCE_CAMPAIGN_ID,
        "name": VALERIA_CADENCE_CAMPAIGN_NAME,
        "description": VALERIA_CADENCE_CAMPAIGN_DESCRIPTION,
        "status": "draft",  # PERMANENTE: espelho nunca executa (guardas no router)
        "env_tag": _ENV_TAG,
        "send_start_hour": 9,
        "send_end_hour": 16,
    }

    ids = {k: _node_id(k) for k in (
        "trigger", "t1", "wait_d1", "window", "t2", "wait_d3", "t3", "wait_d6", "t4",
        "end_done", "reopen", "end_reopen",
    )}

    nodes = [
        {
            "id": ids["trigger"], "type": "trigger",
            "config": {"trigger_type": "no_message", "days": 0},
            "position_x": 0, "position_y": 200,
            "next_node_id": ids["t1"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["t1"], "type": "send_text",
            "config": {
                "message_text": _touch_text(
                    f"T1 · REENGAJAR — mesmo dia, +{t1.jitter_minutes[0]}–{t1.jitter_minutes[1]}min "
                    f"de jitter humano ({_JANELA}). Texto livre gerado pelo LLM em runtime:",
                    t1.objective_prompt,
                    "Fluxo outbound 'sim-e-sumiu': este toque é substituído pelo NUDGE "
                    f"+{int(OUTBOUND_NUDGE.offset.total_seconds() // 3600)}h (dentro da janela de 24h da Meta).",
                ),
                "on_reply": "cancel",
            },
            "position_x": 260, "position_y": 200,
            "next_node_id": ids["wait_d1"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["wait_d1"], "type": "wait",
            "config": {"days": 1, "send_start_hour": 9, "send_end_hour": 16},
            "position_x": 520, "position_y": 200,
            "next_node_id": ids["window"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["window"], "type": "condition",
            # Semântica: lead respondeu nas últimas 24h = janela da Meta ABERTA.
            "config": {"condition_type": "replied_recently", "days": 1},
            "position_x": 780, "position_y": 200,
            "next_node_id": None, "yes_node_id": ids["t2"], "no_node_id": ids["reopen"],
        },
        {
            "id": ids["t2"], "type": "send_text",
            "config": {
                "message_text": _touch_text(
                    "T2 · REFORÇO DE VALOR — D+1 (janela aberta → texto livre):",
                    t2.objective_prompt,
                ),
                "on_reply": "cancel",
            },
            "position_x": 1040, "position_y": 80,
            "next_node_id": ids["wait_d3"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["wait_d3"], "type": "wait",
            "config": {"days": 2, "send_start_hour": 9, "send_end_hour": 16},
            "position_x": 1300, "position_y": 80,
            "next_node_id": ids["t3"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["t3"], "type": "send_text",
            "config": {
                "message_text": _touch_text(
                    "T3 · PROVA SOCIAL — D+3 (a mesma checagem de janela do T2 se aplica):",
                    t3.objective_prompt,
                ),
                "on_reply": "cancel",
            },
            "position_x": 1560, "position_y": 80,
            "next_node_id": ids["wait_d6"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["wait_d6"], "type": "wait",
            "config": {"days": 4, "send_start_hour": 9, "send_end_hour": 16},
            "position_x": 1820, "position_y": 80,
            "next_node_id": ids["t4"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["t4"], "type": "send_text",
            "config": {
                "message_text": _touch_text(
                    "T4 · ÚLTIMA CHAMADA — D+6h20 do início:",
                    t4.objective_prompt,
                ),
                "on_reply": "cancel",
            },
            "position_x": 2080, "position_y": 80,
            "next_node_id": ids["end_done"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["end_done"], "type": "end",
            "config": {"label": "Cadência concluída — contato pausado com elegância", "final_actions": []},
            "position_x": 2340, "position_y": 80,
            "next_node_id": None, "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["reopen"], "type": "send",
            # Valores REAIS do reopen (Rodada 5): template utility aprovado, locale da
            # aprovação e 3 params posicionais determinísticos.
            "config": {
                "template_name": _REOPEN_TEMPLATE_NAME,
                "template_language": _REOPEN_TEMPLATE_LANGUAGE,
                "template_variables": {
                    "1": "{{primeiro_nome}}",
                    "2": _REOPEN_TOPIC,
                    "3": "{{data_ultima_msg_do_lead}}",
                    "__params_type__": "positional",
                },
                "on_reply": "pause",
                "channel_id": None,
            },
            "position_x": 1040, "position_y": 330,
            "next_node_id": ids["end_reopen"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["end_reopen"], "type": "end",
            "config": {
                "label": "Aguardando reabertura — R1: T3/T4 se dobram neste template (contexto vivo por 7 dias)",
                "final_actions": [],
            },
            "position_x": 1300, "position_y": 330,
            "next_node_id": None, "yes_node_id": None, "no_node_id": None,
        },
    ]
    return campaign, nodes


def sync_valeria_cadence_campaign() -> bool:
    """Upsert idempotente do espelho. Chamado no lifespan da API (fail-open).

    Delete+insert dos nós (ids determinísticos) em ORDEM TOPOLÓGICA REVERSA — cada
    next/yes/no_node_id referencia um nó já inserido, então as FKs valem em qualquer
    modo de checagem. Retorna True em sucesso; False (com warning) em falha.
    """
    try:
        campaign, nodes = build_valeria_cadence_graph()
        sb = get_supabase()
        sb.table("campaigns").upsert(campaign, on_conflict="id").execute()
        sb.table("campaign_nodes").delete().eq("campaign_id", campaign["id"]).execute()
        rows = [{**n, "campaign_id": campaign["id"]} for n in reversed(nodes)]
        sb.table("campaign_nodes").insert(rows).execute()
        logger.info(
            "[SYSTEM CADENCE] espelho do motor sincronizado (%d nós) campaign=%s",
            len(rows), campaign["id"],
        )
        return True
    except Exception as exc:
        logger.warning("[SYSTEM CADENCE] sync do espelho falhou (fail-open): %s", exc)
        return False
