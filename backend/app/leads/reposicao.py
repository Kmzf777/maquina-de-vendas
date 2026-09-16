# backend/app/leads/reposicao.py
"""Ciclo de reposição: todo deal que fecha em 'fechado_ganho' garante uma nova
oportunidade aberta para o lead (recompra). Idempotente e fail-soft.

O DESTINO É RESOLVIDO POR UUID, NUNCA POR NOME — ver o comentário acima de
`_ORIGEM_PARA_REPOSICAO` para o incidente que motivou essa escolha.
"""
import logging
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import create_deal

logger = logging.getLogger(__name__)

# Incidente 1 (medido em 09/09/2026): a constante de nome valia 'Reposição - João',
# invertida em relação ao nome real do funil, id 79e35e6b-01d1-482a-bdf0-64c733ff1ca4.
# Incidente 2 (10/09/2026): o nome real do funil mudou (ganhou o sufixo "Atacado") —
# mesmo id, nome novo. Nos dois casos, create_deal resolvia o pipeline pelo NOME
# (`.eq("name", ...)`) e, não achando, caía CALADO no fallback "primeiro pipeline por
# order_index" (histórico: seis funis empatam em order_index = 0). Foi
# assim que 19 deals automáticos de reposição foram parar em "Valeria - Importação
# Leads Frios" entre 07/08 e 04/09/2026, cada um invisível para o João. O nome mudou
# duas vezes e quebrou duas vezes: não pode ser o contrato. UUID não é editável pela
# tela — é o único identificador estável do funil.
#
# Além disso, nome certo não bastaria: em 10/09/2026 passaram a existir DOIS funis de
# reposição (Atacado e Private Label). O destino depende do FUNIL DE ORIGEM do card
# que fechou, não de uma constante única — ver `_ORIGEM_PARA_REPOSICAO` abaixo.

# Mapa origem → destino, por UUID. Confirmado por SELECT em 10/09/2026.
#   João - Atacado         → João - Reposição Atacado
#   João - Private Label   → João - Reposição Private Label
# Qualquer pipeline de origem fora deste mapa é DESCONHECIDO por desenho — ver
# reposicao_pipeline_para().
_ORIGEM_PARA_REPOSICAO: dict[str, str] = {
    "9706a14a-3d9a-413b-bceb-26838fc2cc45": "79e35e6b-01d1-482a-bdf0-64c733ff1ca4",
    "24fb6ce8-6b7b-4612-970d-8debb8c041b7": "9c027143-72f6-42d6-861f-a494ba5bbb4f",
}

# Etapa de destino resolvida por KEY, nunca por rótulo — rótulo é editável pelo
# operador na tela (a mesma lição do nome de pipeline). 'novo' é o marco zero do
# relógio de reposição: `deals.entered_stage_at` (mantido por trigger) vira a data da
# venda quando o card nasce aqui, e é esse relógio que a esteira de 45 dias lê.
_REPOSICAO_STAGE_KEY = "novo"

_WON_KEY = "fechado_ganho"


def reposicao_pipeline_para(pipeline_origem: str | None) -> str | None:
    """Resolve o pipeline_id de Reposição de DESTINO a partir do pipeline de ORIGEM.

    Fail-closed por desenho: origem ausente ou desconhecida (funil novo, id errado,
    None) → None, e o chamador NÃO cria o card. Criar no funil errado é pior que não
    criar — é exatamente o que o fallback silencioso antigo fazia (ver docstring do
    módulo): 19 cards de reposição foram parar em "Valeria - Importação Leads Frios",
    invisíveis para o João. Aqui, origem desconhecida não tem fallback nenhum.
    """
    if not pipeline_origem:
        return None
    return _ORIGEM_PARA_REPOSICAO.get(pipeline_origem)


def _pipeline_de_origem(deal_id: str | None) -> str | None:
    """Lê `deals.pipeline_id` do card que fechou (a ORIGEM da venda).

    Fail-soft: deal_id ausente, deal inexistente ou erro de consulta → None. Quem
    chama (`ensure_reposicao_deal`) já é fail-closed para None — não cria nada — então
    esta função não precisa (e não deve) inventar um destino na ausência do dado.
    """
    if not deal_id:
        return None
    try:
        sb = get_supabase()
        rows = (
            sb.table("deals")
            .select("pipeline_id")
            .eq("id", deal_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0].get("pipeline_id") if rows else None
    except Exception as exc:
        logger.error("_pipeline_de_origem(%s) falhou: %s", deal_id, exc, exc_info=True)
        return None


def ensure_reposicao_deal(lead_id: str, deal_id: str | None = None) -> None:
    """Garante uma oportunidade aberta para o lead no funil de Reposição CORRETO.

    O destino depende do funil de ORIGEM do `deal_id` que fechou — ver
    `reposicao_pipeline_para`. Sem `deal_id`, ou com origem fora do mapa conhecido,
    NÃO cria nada (fail-closed): card no funil errado é um bug silencioso, e já
    produziu um incidente de 19 deals extraviados (09/09/2026). Não criar é visível
    (fica sem card) e revisável; criar errado não é.

    A etapa de destino é resolvida por KEY ('novo'), nunca por rótulo — nascer em
    'novo' é o que zera o relógio dos 45 dias de reposição (deals.entered_stage_at
    vira a data da venda via trigger).

    `dedupe_open` é escopado ao PRÓPRIO funil de reposição de destino
    (`dedupe_pipeline_id`): sem esse escopo, `create_deal` reaproveitaria qualquer
    deal aberto do lead — inclusive um card de handoff da ValerIA aberto num funil
    totalmente diferente — e o card de reposição nunca chegaria a existir.

    Fail-soft no restante: nunca levanta (não pode derrubar o fluxo de venda/Kanban).
    """
    if not lead_id:
        return
    try:
        pipeline_origem = _pipeline_de_origem(deal_id)
        pipeline_destino = reposicao_pipeline_para(pipeline_origem)
        if not pipeline_destino:
            logger.warning(
                "ensure_reposicao_deal(%s, deal=%s): origem %s sem funil de reposição "
                "mapeado — não cria (fail-closed)",
                lead_id, deal_id, pipeline_origem,
            )
            return
        create_deal(
            lead_id,
            title="Reposição",
            pipeline_id=pipeline_destino,
            stage_key=_REPOSICAO_STAGE_KEY,
            dedupe_open=True,
            dedupe_pipeline_id=pipeline_destino,
        )
    except Exception as exc:
        logger.error("ensure_reposicao_deal(%s) falhou: %s", lead_id, exc, exc_info=True)


def deal_is_won(deal_id: str) -> bool:
    """True se o stage atual do deal tem key 'fechado_ganho'. Fail-soft → False em erro."""
    if not deal_id:
        return False
    try:
        sb = get_supabase()
        deal = sb.table("deals").select("stage_id").eq("id", deal_id).limit(1).execute().data
        if not deal:
            return False
        stage_id = deal[0].get("stage_id")
        if not stage_id:
            return False
        stage = sb.table("pipeline_stages").select("key").eq("id", stage_id).limit(1).execute().data
        return bool(stage) and stage[0].get("key") == _WON_KEY
    except Exception as exc:
        logger.error("deal_is_won(%s) falhou: %s", deal_id, exc, exc_info=True)
        return False
