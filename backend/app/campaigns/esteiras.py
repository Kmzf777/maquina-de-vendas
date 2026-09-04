"""Seed das esteiras do vendedor (itens 6, 7 e 8 da ata de 03/09/2026).

Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md

DIFERENCA ESSENCIAL para `system_cadence.py`: aquele modulo e um ESPELHO read-only,
re-sincronizado a cada deploy e desfazendo edicao manual. Este cria a campanha UMA VEZ
e nunca mais toca — porque a decisao do dono e que o Arthur e o Joao editem prazo e
template pela tela, sem deploy. O seed e idempotente por EXISTENCIA do id, nao por
conteudo.

As campanhas nascem `draft` (desligadas) de proposito: os templates da Meta ainda podem
estar em aprovacao, e ligar a esteira de reposicao num banco com meses de cards parados
torna elegivel, de uma vez, todo card com mais de 15 dias.

O que o seed NAO preenche (fica para a tela, §8 da spec): canal, funil, etapa de gatilho
e a etapa de destino do `mark_deal_lost`. Sao valores por instalacao — a esteira e por
funil e canal, nunca amarrada num vendedor especifico.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.campaigns.service import _ENV_TAG
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_NS = "canastra://system/esteiras-vendedor"

# Nome que entra no parametro {{2}} dos templates ("Aqui e o {{2}}, do Cafe Canastra").
# LITERAL, nao token: o caminho de envio de TEMPLATE resolve variaveis por
# `broadcast.worker._resolve_value`, que so conhece {{primeiro_nome}}, {{nome_completo}},
# {{telefone}} e {{empresa}}. `{{vendedor}}` existe apenas em
# `automation.variables.substitute_variables` (texto livre e alertas) — num parametro de
# template ele iria LITERALMENTE para o cliente. Trocar aqui (ou no builder) quando o
# dono do numero mudar.
_VENDEDOR = "João"

# Janela de envio das quatro campanhas. O default da coluna e 7h–18h; 7h da manha e cedo
# demais para retomada comercial e a tela nao expoe esse campo hoje.
_SEND_START_HOUR = 9
_SEND_END_HOUR = 18


def _campaign_id(key: str, env_tag: str) -> str:
    """UUID determinístico por (esteira, ambiente) — função PURA.

    O `env_tag` entra no namespace de proposito. Dev e producao apontam para o MESMO
    Supabase; com um id fixo, o primeiro ambiente a subir criaria a linha com o seu
    env_tag e o outro veria o id existente, pularia o seed e nunca teria as campanhas
    no seu proprio env_tag — `get_campaigns_with_trigger_type` filtra por env_tag,
    entao a esteira ficaria ativa na tela e muda no motor.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{env_tag}/{key}"))


def _cid(key: str) -> str:
    return _campaign_id(key, _ENV_TAG)


def _nid(key: str, no: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{_ENV_TAG}/{key}/{no}"))


# O encadeamento dos nos e POSICIONAL: a lista `nodes` de cada esteira esta em ordem
# linear e `build_node_rows` liga cada no ao seguinte. Nao existe campo "next" nos
# helpers de proposito — duas fontes de verdade para a mesma aresta seria bug garantido.
def _trigger(key: str, *, stage_days: int, silence_days: int, last_speaker: str,
             stage_key: str | None = None) -> dict[str, Any]:
    return {
        "id": _nid(key, "trigger"), "type": "trigger",
        "config": {
            "trigger_type": "deal_stage_stagnation",
            "stage_id": None,       # preenchido na tela
            "stage_key": stage_key, # 'proposta_enviada' na E3; None nas outras
            "pipeline_id": None,    # preenchido na tela
            "stage_days": stage_days,
            "silence_days": silence_days,
            "last_speaker": last_speaker,
            "limit": 20,
            # Politica de resposta da esteira INTEIRA. Nos nos de envio nao basta:
            # `worker.handle_campaign_reply` so olhava o `on_reply` do no atual, e uma
            # esteira passa a maior parte da vida parada num `wait` — que e onde a
            # maioria das respostas chega. Ali o default 'pause' deixaria o enrollment
            # em estado que `is_already_enrolled` conta como ativo e ninguem retoma:
            # o lead ficaria inelegivel para sempre. Um `send` com valor proprio
            # continua vencendo este.
            "on_reply": "cancel",
        },
    }


def _send(key: str, no: str, template: str) -> dict[str, Any]:
    return {
        "id": _nid(key, no), "type": "send",
        "config": {
            "template_name": template,
            "template_language": "pt_BR",  # conferir o locale APROVADO — ver spec §7
            "template_variables": {
                "1": "{{primeiro_nome}}",
                "2": _VENDEDOR,
                # Os 5 templates da spec §7 usam {{1}}/{{2}} posicionais. Sem esta
                # chave, `_build_template_components` monta parametros NOMEADOS
                # (`parameter_name`) e a Meta recusa o envio.
                "__params_type__": "positional",
            },
            # 'pause' (o default do motor) deixaria o lead inelegivel para sempre:
            # enrollment pausado conta como ativo em is_already_enrolled e nunca e
            # retomado. 'cancel' deixa o lead sair limpo e poder voltar depois.
            "on_reply": "cancel",
        },
    }


def _wait(key: str, no: str, dias: int) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "wait", "config": {"days": dias}}


def _action(key: str, no: str, cfg: dict) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "action", "config": cfg}


def _end(key: str, no: str) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "end", "config": {"final_actions": []}}


def _esteira(key: str, nome: str, descricao: str, priority: int, nodes: list[dict]) -> dict[str, Any]:
    return {
        "key": key,
        "campaign_id": _cid(key),
        "name": nome,
        "description": descricao,
        "status": "draft",
        "audience": "humano",
        "priority": priority,
        "frequency_cap": 1,
        "nodes": nodes,
    }


# E1a — o lead perguntou e ninguem respondeu.
_NOVO_SEM_RESPOSTA = _esteira(
    "novo_sem_resposta",
    "Esteira — Novo sem resposta nossa",
    "Card na etapa inicial, ultima mensagem do LEAD, 3 dias sem resposta. Manda o "
    "template de retomada e alerta o vendedor. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_sem_resposta", stage_days=0, silence_days=3, last_speaker="lead"),
        _send("novo_sem_resposta", "t1", "esteira_novo_sem_resposta_v1"),
        _action("novo_sem_resposta", "a1", {
            "action_type": "alert_seller",
            "severity": "warning",
            "title": "Lead sem resposta ha 3 dias",
            "message_template": "{{nome}} perguntou e ficou sem resposta. Template de retomada enviado.",
        }),
        _end("novo_sem_resposta", "fim"),
    ],
)

# E1b — atendemos e o lead sumiu.
_NOVO_REENGAJAMENTO = _esteira(
    "novo_reengajamento",
    "Esteira — Novo, lead sumiu",
    "Card na etapa inicial, ultima mensagem NOSSA, 3 dias sem retorno do lead. "
    "Um toque de reengajamento. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_reengajamento", stage_days=0, silence_days=3, last_speaker="nos"),
        _send("novo_reengajamento", "t1", "esteira_novo_reengajamento_v1"),
        _end("novo_reengajamento", "fim"),
    ],
)

# E2 — reposicao: 3 ciclos de 15 dias e o card vira Perdido.
_REPOSICAO = _esteira(
    "reposicao",
    "Esteira — Reposicao",
    "Card na etapa configurada, 15 dias sem conversa. Ate 3 toques de 15 em 15 dias; "
    "no terceiro silencio o card vai para Perdido. Sai sozinha se o card mudar de coluna.",
    priority=4,
    nodes=[
        _trigger("reposicao", stage_days=0, silence_days=15, last_speaker="qualquer"),
        _send("reposicao", "t1", "esteira_reposicao_v1"),
        _wait("reposicao", "w1", 15),
        _send("reposicao", "t2", "esteira_reposicao_v1"),
        _wait("reposicao", "w2", 15),
        _send("reposicao", "t3", "esteira_reposicao_v1"),
        _wait("reposicao", "w3", 15),
        _action("reposicao", "a1", {
            "action_type": "mark_deal_lost",
            # Sem stage_id a acao e um no-op silencioso (`_execute_action` retorna cedo).
            # E o comportamento desejado ate a tela apontar a etapa Perdido do funil:
            # um seed nao pode adivinhar qual e o id de "perdido" em cada instalacao.
            "stage_id": None,
            "lost_reason": "sem resposta na esteira de reposicao",
        }),
        _end("reposicao", "fim"),
    ],
)

# E3 — follow-up de proposta: 2 toques e alerta. Nunca move o card.
_PROPOSTA = _esteira(
    "proposta",
    "Esteira — Follow-up de proposta",
    "Card em Proposta Enviada ha 3 dias sem resposta do cliente. Toque em D+3 e D+8; "
    "depois alerta o vendedor. NUNCA move o card sozinho.",
    priority=8,
    nodes=[
        _trigger("proposta", stage_days=3, silence_days=0, last_speaker="nos",
                 stage_key="proposta_enviada"),
        _send("proposta", "t1", "esteira_proposta_d3_v1"),
        _wait("proposta", "w1", 5),
        _send("proposta", "t2", "esteira_proposta_d8_v1"),
        _wait("proposta", "w2", 2),
        _action("proposta", "a1", {
            "action_type": "alert_seller",
            "severity": "warning",
            "title": "Proposta esfriando",
            "message_template": "{{nome}} nao respondeu a proposta ha 10 dias. Card segue em Proposta Enviada.",
        }),
        _end("proposta", "fim"),
    ],
)

ESTEIRAS: tuple[dict[str, Any], ...] = (
    _NOVO_SEM_RESPOSTA, _NOVO_REENGAJAMENTO, _REPOSICAO, _PROPOSTA,
)


def build_node_rows(esteira: dict[str, Any]) -> list[dict[str, Any]]:
    """Linhas de `campaign_nodes` da esteira, prontas para INSERT — função PURA.

    Devolve em ORDEM TOPOLOGICA REVERSA (do `end` para o `trigger`): o FK
    `next_node_id` aponta para a propria tabela, entao o alvo precisa existir antes.
    Mesmo padrao de `system_cadence.sync_valeria_cadence_campaign`.

    O encadeamento sai da POSICAO na lista `nodes` — cada no aponta para o seguinte.
    """
    nodes = esteira["nodes"]
    rows = []
    for i, no in enumerate(nodes):
        rows.append({
            "id": no["id"],
            "campaign_id": esteira["campaign_id"],
            "type": no["type"],
            "config": no["config"],
            "position_x": 300 * i,
            "position_y": 200,
            "next_node_id": nodes[i + 1]["id"] if i + 1 < len(nodes) else None,
            "yes_node_id": None,
            "no_node_id": None,
        })
    return list(reversed(rows))


def _campaign_row(esteira: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": esteira["campaign_id"],
        "name": esteira["name"],
        "description": esteira["description"],
        "status": esteira["status"],
        "env_tag": _ENV_TAG,
        "audience": esteira["audience"],
        "priority": esteira["priority"],
        "frequency_cap": esteira["frequency_cap"],
        "send_start_hour": _SEND_START_HOUR,
        "send_end_hour": _SEND_END_HOUR,
    }


def _tem_nos(sb, campaign_id: str) -> bool:
    return bool(
        sb.table("campaign_nodes").select("id")
        .eq("campaign_id", campaign_id).limit(1).execute().data
    )


def seed_esteiras() -> None:
    """Cria as campanhas que ainda nao existem. NUNCA sobrescreve. Fail-soft.

    Idempotencia por EXISTENCIA do id: campanha ja criada e territorio do dono (prazo,
    template e etapa saem da tela) e o seed nao encosta nela. A unica excecao e a
    campanha que existe SEM nenhum no — estado que so aparece quando um seed anterior
    morreu entre o insert da campanha e o dos nos; sem esta reparacao, a idempotencia
    por id deixaria essa campanha vazia para sempre.
    """
    try:
        sb = get_supabase()
        ids = [e["campaign_id"] for e in ESTEIRAS]
        existentes = {
            r["id"] for r in
            (sb.table("campaigns").select("id").in_("id", ids).execute().data or [])
        }
    except Exception as exc:
        logger.error("[ESTEIRAS] seed falhou ao consultar campanhas: %s", exc, exc_info=True)
        return

    for e in ESTEIRAS:
        # Uma esteira que falha nao pode levar as outras junto (ex.: a coluna
        # `audience` da migration 20260904 ainda nao aplicada derruba o insert).
        try:
            nova = e["campaign_id"] not in existentes
            if nova:
                sb.table("campaigns").insert(_campaign_row(e)).execute()
            elif _tem_nos(sb, e["campaign_id"]):
                continue
            sb.table("campaign_nodes").insert(build_node_rows(e)).execute()
            logger.info(
                "[ESTEIRAS] campanha '%s' %s (draft, %d nos) id=%s",
                e["name"], "criada" if nova else "reparada (estava sem nos)",
                len(e["nodes"]), e["campaign_id"],
            )
        except Exception as exc:
            logger.error("[ESTEIRAS] seed da esteira '%s' falhou: %s", e["key"], exc, exc_info=True)
