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
    - INVARIANTE DA JANELA DE 24h (Meta): NENHUM texto livre sem uma checagem de
      janela imediatamente antes. O motor real checa a janela no fire-time de CADA
      toque (fechada → template de reabertura); o grafo espelha isso com uma
      condition `replied_recently days=1` ("lead respondeu nas últimas 24h" =
      janela aberta) na frente de CADA send_text, e TODOS os ramos NÃO convergem no
      mesmo nó de template de reabertura (com os valores REAIS do scheduler).
    - `on_reply: "cancel"` nos toques livres = resposta do lead cancela/re-arma a
      cadência (comportamento real de schedule_followup).
    - Depois do template de reabertura vale a R1: os toques seguintes se dobram nele
      — por isso o ramo termina em `end` "aguardando reabertura".
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
        "trigger",
        "cond_t1", "t1", "wait_d1",
        "cond_t2", "t2", "wait_d3",
        "cond_t3", "t3", "wait_d6",
        "cond_t4", "t4",
        "end_done", "reopen", "end_reopen",
    )}

    def _window_condition(key: str, x: int, yes_key: str) -> dict:
        """Checagem de janela na frente de CADA toque livre (invariante da Meta):
        lead respondeu nas últimas 24h = janela ABERTA → texto livre; senão → o nó
        único de template de reabertura (todos os ramos NÃO convergem nele)."""
        return {
            "id": ids[key], "type": "condition",
            "config": {"condition_type": "replied_recently", "days": 1},
            "position_x": x, "position_y": 200,
            "next_node_id": None, "yes_node_id": ids[yes_key], "no_node_id": ids["reopen"],
        }

    def _free_touch(key: str, x: int, header: str, prompt: str, next_key: str, footer: str | None = None) -> dict:
        return {
            "id": ids[key], "type": "send_text",
            "config": {"message_text": _touch_text(header, prompt, footer), "on_reply": "cancel"},
            "position_x": x, "position_y": 60,
            "next_node_id": ids[next_key], "yes_node_id": None, "no_node_id": None,
        }

    def _wait(key: str, x: int, days: int, next_key: str) -> dict:
        return {
            "id": ids[key], "type": "wait",
            "config": {"days": days, "send_start_hour": 9, "send_end_hour": 16},
            "position_x": x, "position_y": 200,
            "next_node_id": ids[next_key], "yes_node_id": None, "no_node_id": None,
        }

    _guard_note = "Texto livre SÓ sai com a janela de 24h da Meta aberta — a checagem é o nó anterior; fechada, sai o template de reabertura."

    nodes = [
        {
            "id": ids["trigger"], "type": "trigger",
            "config": {"trigger_type": "no_message", "days": 0},
            "position_x": 0, "position_y": 200,
            "next_node_id": ids["cond_t1"], "yes_node_id": None, "no_node_id": None,
        },
        _window_condition("cond_t1", 260, "t1"),
        _free_touch(
            "t1", 260,
            f"T1 · REENGAJAR — mesmo dia, +{t1.jitter_minutes[0]}–{t1.jitter_minutes[1]}min "
            f"de jitter humano ({_JANELA}). {_guard_note} Texto gerado pelo LLM em runtime:",
            t1.objective_prompt,
            "wait_d1",
            "Fluxo outbound 'sim-e-sumiu': este toque é substituído pelo NUDGE "
            f"+{int(OUTBOUND_NUDGE.offset.total_seconds() // 3600)}h (dentro da janela de 24h da Meta).",
        ),
        _wait("wait_d1", 560, 1, "cond_t2"),
        _window_condition("cond_t2", 860, "t2"),
        _free_touch("t2", 860, f"T2 · REFORÇO DE VALOR — D+1. {_guard_note}", t2.objective_prompt, "wait_d3"),
        _wait("wait_d3", 1160, 2, "cond_t3"),
        _window_condition("cond_t3", 1460, "t3"),
        _free_touch("t3", 1460, f"T3 · PROVA SOCIAL — D+3. {_guard_note}", t3.objective_prompt, "wait_d6"),
        _wait("wait_d6", 1760, 4, "cond_t4"),
        _window_condition("cond_t4", 2060, "t4"),
        _free_touch("t4", 2060, f"T4 · ÚLTIMA CHAMADA — D+6h20 do início. {_guard_note}", t4.objective_prompt, "end_done"),
        {
            "id": ids["end_done"], "type": "end",
            "config": {"label": "Cadência concluída — contato pausado com elegância", "final_actions": []},
            "position_x": 2360, "position_y": 60,
            "next_node_id": None, "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["reopen"], "type": "send",
            # Valores REAIS do reopen (Rodada 5): template utility aprovado, locale da
            # aprovação e 3 params posicionais determinísticos. É o ÚNICO formato
            # permitido pela Meta com a janela de 24h fechada — todos os ramos NÃO
            # das checagens de janela convergem aqui.
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
            "position_x": 1160, "position_y": 400,
            "next_node_id": ids["end_reopen"], "yes_node_id": None, "no_node_id": None,
        },
        {
            "id": ids["end_reopen"], "type": "end",
            "config": {
                "label": "Aguardando reabertura — R1: os toques seguintes se dobram neste template (contexto vivo por 7 dias)",
                "final_actions": [],
            },
            "position_x": 1460, "position_y": 400,
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
