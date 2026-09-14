"""Seed das 6 esteiras do vendedor Joao (reuniao de 10/09/2026 — Task 9 do plano
"o motor de follow-up do vendedor").

DIFERENCA para `esteiras.py` (o seed generico das 4 esteiras antigas): aquele nao sabe
o canal/funil da instalacao e deixa `channel_id`/`pipeline_id` em None, "preenchido na
tela". Este AQUI e amarrado a um vendedor especifico de proposito — a reuniao decidiu o
desenho para o Joao, com os funis, o canal e as etapas de destino dele ja conhecidos
(tabela abaixo) — entao o seed ja nasce com `pipeline_id`, `channel_id` e o `stage_id`
de destino (`em_atencao`) corretos, um por funil. So o TEMPLATE fica para a tela: os 5
textos da reuniao ainda nao foram submetidos a aprovacao da Meta.

Mesmo padrao do `esteiras.py`: UUID determinístico por `uuid5` incluindo o `env_tag` no
namespace (dev e producao apontam para o MESMO Supabase; sem o env_tag, o primeiro
ambiente a subir carimbaria a linha e o outro nunca veria a campanha — ver
`_campaign_id` abaixo), idempotencia por EXISTENCIA do id (nunca sobrescreve — prazo e
template saem da tela, nao de um redeploy) e fail-soft POR ESTEIRA (uma que falhar nao
pode levar as outras cinco).

Decisoes da reuniao de 10/09/2026 que este seed materializa:

- "Novo" — card parado na etapa `novo`. A ata registrou "36h a dois dias"; usamos DOIS
  DIAS porque `deal_stage_stagnation` e o UNICO gatilho completo do sistema — o unico
  com guarda de blacklist, numero errado e conversa finalizada (ver
  `get_deals_stage_stagnant` em `supabase/migrations/20260904_esteiras_vendedor.sql`) —
  e a RPC so entende dias inteiros (`p_stage_days int`), sem granularidade de horas.
  Ganhar 36h custaria um gatilho novo, sem as guardas do que ja existe; dois dias esta
  dentro do que o dono aprovou. Um unico toque, nao move o card.
- "Em conversa" — 7 toques em 30 dias (D+2, D+4, D+7, D+12, D+18, D+24, D+30), com
  `on_reply='reset'`: qualquer resposta do lead volta o relogio para D+0
  (`worker.reset_enrollment`, adicionado numa task anterior deste plano). Termina
  movendo o card para `em_atencao`.
- "Reposicao" — card em "Cliente Ativo" (key `novo` do funil de reposicao) ha 45 dias,
  depois toques de 3, 15 e 15 dias. Termina movendo o card para `em_atencao`.

Cada esteira existe DUAS VEZES — Atacado e Private Label — porque o gatilho e por funil
(`pipeline_id`) e as mensagens diferem entre as linhas. Seis campanhas ao todo.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.campaigns.service import _ENV_TAG
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_NS = "canastra://system/esteiras-joao"

# UUIDs de producao (reuniao de 10/09/2026) — funis do Joao e o canal dele.
PIPELINE_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PIPELINE_PRIVATE_LABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
PIPELINE_REPOSICAO_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"
PIPELINE_REPOSICAO_PRIVATE_LABEL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"
CANAL_JOAO = "a3a607b1-6bff-4370-8609-b275eef270dd"

# stage_id (nao key) da etapa "Em atencao" de CADA funil — medido em producao. Ver
# `_mover_para_em_atencao` para o porque de ser stage_id e nao stage_key: o motor
# (`automation/engine.py::_execute_action`) so le `stage_id`, sem fallback por key.
STAGE_EM_ATENCAO_ATACADO = "db9c9955-df87-4e0f-99ce-8e97039063a6"
STAGE_EM_ATENCAO_PRIVATE_LABEL = "e7f4a1ee-0785-4f43-b6db-c1b846255b03"
STAGE_EM_ATENCAO_REPOSICAO_ATACADO = "499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0"
STAGE_EM_ATENCAO_REPOSICAO_PRIVATE_LABEL = "6a232838-221a-4e10-b2e1-100581e63601"

# Janela de envio (ajustada 13/09/2026, pedido do dono): 8h-12h, so dias uteis. O
# Joao trabalha das 9h as 16h, entao o disparo sai de manha para a resposta do lead
# cair dentro do expediente dele — sabado/domingo ele nao esta la para responder.
_SEND_START_HOUR = 8
_SEND_END_HOUR = 12
_SKIP_WEEKENDS = True


def _campaign_id(key: str, env_tag: str) -> str:
    """UUID determinístico por (esteira, ambiente) — função PURA.

    O `env_tag` entra no namespace de proposito — mesmo motivo do `esteiras.py`: dev e
    producao compartilham o mesmo Supabase, e sem isto o primeiro ambiente a subir
    deixaria o outro sem campanha (`get_campaigns_with_trigger_type` filtra por
    env_tag).
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{env_tag}/{key}"))


def _cid(key: str) -> str:
    return _campaign_id(key, _ENV_TAG)


def _nid(key: str, no: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{_ENV_TAG}/{key}/{no}"))


# O encadeamento dos nos e POSICIONAL: a lista `nodes` de cada esteira esta em ordem
# linear e `build_node_rows` liga cada no ao seguinte — mesmo padrao do esteiras.py.
def _trigger(key: str, *, stage_key: str, stage_days: int, pipeline_id: str,
             on_reply: str = "cancel") -> dict[str, Any]:
    return {
        "id": _nid(key, "trigger"), "type": "trigger",
        "config": {
            "trigger_type": "deal_stage_stagnation",
            "stage_id": None,        # id exato da coluna — preenchido na tela
            "stage_key": stage_key,
            "pipeline_id": pipeline_id,  # conhecido (tabela de producao da reuniao)
            "stage_days": stage_days,
            # As tres esteiras do Joao medem tempo na ETAPA, nao silencio de conversa —
            # e por isso que da para usar o mesmo gatilho para as tres, so trocando
            # stage_key/stage_days. silence_days<=0 na RPC significa "sem filtro".
            "silence_days": 0,
            "last_speaker": "qualquer",
            "limit": 20,
            # Politica de resposta da esteira INTEIRA — `worker._trigger_on_reply` le
            # este campo quando o NO atual (send/wait) nao tem o seu proprio, o que
            # cobre a maior parte da vida do enrollment (parado num `wait`).
            "on_reply": on_reply,
        },
    }


def _send(key: str, no: str) -> dict[str, Any]:
    return {
        "id": _nid(key, no), "type": "send",
        "config": {
            # STRING VAZIA de proposito: template e responsabilidade do dono,
            # preenchida na tela — e ligar a esteira exige template APROVADO pela Meta
            # (os 5 textos da reuniao de 10/09/2026 ainda nao foram submetidos).
            "template_name": "",
            "template_language": "pt_BR",
            "template_variables": {},
            # SEM "on_reply" aqui, DE PROPOSITO — nao e omissao. `esteiras.py`
            # (generico) grava 'cancel' em todo `send`, redundante com o gatilho ali
            # (que tambem e sempre 'cancel'). Aqui seria uma ARMADILHA:
            # `worker._apply_reply_policy` da precedencia ao NO sobre o GATILHO, e a
            # esteira "Em conversa" precisa do 'reset' do gatilho valendo em TODO
            # toque. Um 'cancel' hardcoded no `send` mataria o reset em silencio — o
            # enrollment cancelaria na primeira resposta em vez de rebobinar. A
            # politica vive so no gatilho; todo `send` herda dele.
        },
    }


def _wait(key: str, no: str, dias: int) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "wait", "config": {"days": dias}}


def _mover_para_em_atencao(key: str, no: str, stage_id: str) -> dict[str, Any]:
    return {
        "id": _nid(key, no), "type": "action",
        "config": {
            "action_type": "move_deal_stage",
            # HARDCODED (medido em producao — ver STAGE_EM_ATENCAO_* acima), nao None.
            # `engine._execute_action` so LE `stage_id`; nao existe fallback por
            # `stage_key` no motor. Com `stage_id: None` a acao era um no-op
            # SILENCIOSO: os toques saiam normalmente, mas o card nunca se movia para
            # "Em atencao" — o estado terminal que a reuniao pediu. Mesmo racional dos
            # UUIDs de funil/canal acima: hardcode e mais seguro que nome/key aqui,
            # porque a KEY e editavel pela tela e ja quebrou este sistema duas vezes.
            "stage_id": stage_id,
            # `stage_key` fica ao lado so como DOCUMENTACAO da intencao, para quem for
            # ler o grafo entender qual etapa e essa — o motor le exclusivamente
            # `stage_id` acima, nunca esta chave.
            "stage_key": "em_atencao",
        },
    }


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
        "channel_id": CANAL_JOAO,
        "nodes": nodes,
    }


# ── "Novo" — stage_days=2 na etapa 'novo', um toque, nao move o card ────────────

_NOVO_ATACADO = _esteira(
    "novo_atacado",
    "Esteira Joao — Novo (Atacado)",
    "Card parado 2 dias na etapa 'novo' do funil Joao - Atacado. Um toque de "
    "retomada. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_atacado", stage_key="novo", stage_days=2, pipeline_id=PIPELINE_ATACADO),
        _send("novo_atacado", "t1"),
        _end("novo_atacado", "fim"),
    ],
)

_NOVO_PRIVATE_LABEL = _esteira(
    "novo_private_label",
    "Esteira Joao — Novo (Private Label)",
    "Card parado 2 dias na etapa 'novo' do funil Joao - Private Label. Um toque de "
    "retomada. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_private_label", stage_key="novo", stage_days=2, pipeline_id=PIPELINE_PRIVATE_LABEL),
        _send("novo_private_label", "t1"),
        _end("novo_private_label", "fim"),
    ],
)

# ── "Em conversa" — 7 toques em 30 dias, on_reply='reset', termina em em_atencao ──


def _em_conversa_nodes(key: str, pipeline_id: str, em_atencao_stage_id: str) -> list[dict]:
    # D+2, D+4, D+7, D+12, D+18, D+24, D+30 a partir da entrada na etapa 'respondeu'.
    # O toque 1 sai no proprio disparo do gatilho (stage_days=2); os seis toques
    # seguintes usam `wait` com os deltas restantes: 2, 3, 5, 6, 6, 6.
    return [
        _trigger(key, stage_key="respondeu", stage_days=2, pipeline_id=pipeline_id, on_reply="reset"),
        _send(key, "t1"),
        _wait(key, "w1", 2),
        _send(key, "t2"),
        _wait(key, "w2", 3),
        _send(key, "t3"),
        _wait(key, "w3", 5),
        _send(key, "t4"),
        _wait(key, "w4", 6),
        _send(key, "t5"),
        _wait(key, "w5", 6),
        _send(key, "t6"),
        _wait(key, "w6", 6),
        _send(key, "t7"),
        # SEMPRE o em_atencao do MESMO funil do gatilho (`pipeline_id` acima) — as
        # quatro esteiras que terminam em em_atencao tem quatro destinos distintos,
        # nunca compartilhados entre funis. Trocar os dois moveria o card pro funil
        # errado.
        _mover_para_em_atencao(key, "a1", em_atencao_stage_id),
        _end(key, "fim"),
    ]


_EM_CONVERSA_ATACADO = _esteira(
    "em_conversa_atacado",
    "Esteira Joao — Em conversa (Atacado)",
    "7 toques em 30 dias (D+2/4/7/12/18/24/30) na etapa 'respondeu' do funil Joao - "
    "Atacado. Qualquer resposta do lead volta o relogio para D+0 (on_reply=reset). "
    "Termina movendo o card para 'em_atencao'.",
    priority=7,
    nodes=_em_conversa_nodes("em_conversa_atacado", PIPELINE_ATACADO, STAGE_EM_ATENCAO_ATACADO),
)

_EM_CONVERSA_PRIVATE_LABEL = _esteira(
    "em_conversa_private_label",
    "Esteira Joao — Em conversa (Private Label)",
    "7 toques em 30 dias (D+2/4/7/12/18/24/30) na etapa 'respondeu' do funil Joao - "
    "Private Label. Qualquer resposta do lead volta o relogio para D+0 "
    "(on_reply=reset). Termina movendo o card para 'em_atencao'.",
    priority=7,
    nodes=_em_conversa_nodes(
        "em_conversa_private_label", PIPELINE_PRIVATE_LABEL, STAGE_EM_ATENCAO_PRIVATE_LABEL,
    ),
)

# ── "Reposicao" — stage_days=45, toques de 3/15/15, termina em em_atencao ───────


def _reposicao_nodes(key: str, pipeline_id: str, em_atencao_stage_id: str) -> list[dict]:
    # Card em "Cliente Ativo" (key 'novo' do funil de reposicao) ha 45 dias -> toque
    # imediato, depois D+3, D+18(+15), D+33(+15).
    return [
        _trigger(key, stage_key="novo", stage_days=45, pipeline_id=pipeline_id),
        _send(key, "t1"),
        _wait(key, "w1", 3),
        _send(key, "t2"),
        _wait(key, "w2", 15),
        _send(key, "t3"),
        _wait(key, "w3", 15),
        _send(key, "t4"),
        # SEMPRE o em_atencao do MESMO funil de reposicao do gatilho — ver o
        # comentario equivalente em `_em_conversa_nodes`.
        _mover_para_em_atencao(key, "a1", em_atencao_stage_id),
        _end(key, "fim"),
    ]


_REPOSICAO_ATACADO = _esteira(
    "reposicao_atacado",
    "Esteira Joao — Reposicao (Atacado)",
    "Card em 'Cliente Ativo' (etapa 'novo' do funil Joao - Reposicao Atacado) ha 45 "
    "dias. Toque imediato, depois D+3, D+18 e D+33. Termina movendo o card para "
    "'em_atencao'.",
    priority=4,
    nodes=_reposicao_nodes(
        "reposicao_atacado", PIPELINE_REPOSICAO_ATACADO, STAGE_EM_ATENCAO_REPOSICAO_ATACADO,
    ),
)

_REPOSICAO_PRIVATE_LABEL = _esteira(
    "reposicao_private_label",
    "Esteira Joao — Reposicao (Private Label)",
    "Card em 'Cliente Ativo' (etapa 'novo' do funil Joao - Reposicao Private Label) "
    "ha 45 dias. Toque imediato, depois D+3, D+18 e D+33. Termina movendo o card "
    "para 'em_atencao'.",
    priority=4,
    nodes=_reposicao_nodes(
        "reposicao_private_label", PIPELINE_REPOSICAO_PRIVATE_LABEL,
        STAGE_EM_ATENCAO_REPOSICAO_PRIVATE_LABEL,
    ),
)

ESTEIRAS_JOAO: tuple[dict[str, Any], ...] = (
    _NOVO_ATACADO, _NOVO_PRIVATE_LABEL,
    _EM_CONVERSA_ATACADO, _EM_CONVERSA_PRIVATE_LABEL,
    _REPOSICAO_ATACADO, _REPOSICAO_PRIVATE_LABEL,
)


def build_node_rows(esteira: dict[str, Any]) -> list[dict[str, Any]]:
    """Linhas de `campaign_nodes` da esteira, prontas para INSERT — função PURA.

    Devolve em ORDEM TOPOLOGICA REVERSA (do `end` para o `trigger`): o FK
    `next_node_id` aponta para a propria tabela, entao o alvo precisa existir antes.
    Mesmo padrao de `esteiras.py`/`system_cadence.sync_valeria_cadence_campaign`.

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
        "channel_id": esteira["channel_id"],
        "send_start_hour": _SEND_START_HOUR,
        "send_end_hour": _SEND_END_HOUR,
        "skip_weekends": _SKIP_WEEKENDS,
    }


def _tem_nos(sb, campaign_id: str) -> bool:
    return bool(
        sb.table("campaign_nodes").select("id")
        .eq("campaign_id", campaign_id).limit(1).execute().data
    )


def seed_esteiras_joao() -> None:
    """Cria as 6 campanhas do Joao que ainda nao existem. NUNCA sobrescreve. Fail-soft.

    Idempotencia por EXISTENCIA do id, mesma doutrina do `esteiras.seed_esteiras`:
    campanha ja criada e territorio do dono (prazo e template saem da tela) e o seed
    nao encosta nela. A unica excecao e a campanha que existe SEM nenhum no — estado
    que so aparece quando um seed anterior morreu entre o insert da campanha e o dos
    nos; sem esta reparacao, a idempotencia por id deixaria essa campanha vazia para
    sempre.
    """
    try:
        sb = get_supabase()
        ids = [e["campaign_id"] for e in ESTEIRAS_JOAO]
        existentes = {
            r["id"] for r in
            (sb.table("campaigns").select("id").in_("id", ids).execute().data or [])
        }
    except Exception as exc:
        logger.error("[ESTEIRAS_JOAO] seed falhou ao consultar campanhas: %s", exc, exc_info=True)
        return

    for e in ESTEIRAS_JOAO:
        # Uma esteira que falha nao pode levar as outras junto (ex.: a coluna
        # `channel_id`/`audience` ainda nao aplicada derruba so este insert).
        try:
            nova = e["campaign_id"] not in existentes
            if nova:
                sb.table("campaigns").insert(_campaign_row(e)).execute()
            elif _tem_nos(sb, e["campaign_id"]):
                continue
            sb.table("campaign_nodes").insert(build_node_rows(e)).execute()
            logger.info(
                "[ESTEIRAS_JOAO] campanha '%s' %s (draft, %d nos) id=%s",
                e["name"], "criada" if nova else "reparada (estava sem nos)",
                len(e["nodes"]), e["campaign_id"],
            )
        except Exception as exc:
            logger.error("[ESTEIRAS_JOAO] seed da esteira '%s' falhou: %s", e["key"], exc, exc_info=True)
