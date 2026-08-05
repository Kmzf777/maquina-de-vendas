# backend/app/leads/reposicao.py
"""Ciclo de reposição: todo deal que fecha em 'fechado_ganho' garante uma nova
oportunidade aberta para o lead (recompra). Idempotente e fail-soft."""
import logging
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import create_deal

logger = logging.getLogger(__name__)

REPOSICAO_PIPELINE_NAME = "Reposição - João"
_WON_KEY = "fechado_ganho"


def ensure_reposicao_deal(lead_id: str) -> None:
    """Garante uma oportunidade aberta para o lead (cria no pipeline de Reposição se não houver).

    `create_deal(dedupe_open=True)` reaproveita qualquer deal aberto do lead → nunca duplica.
    Fail-soft: nunca levanta (não pode derrubar o fluxo de venda/Kanban).
    """
    if not lead_id:
        return
    try:
        create_deal(
            lead_id,
            title="Reposição",
            pipeline_name=REPOSICAO_PIPELINE_NAME,
            dedupe_open=True,
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
