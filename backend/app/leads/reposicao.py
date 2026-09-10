# backend/app/leads/reposicao.py
"""Ciclo de reposição: todo deal que fecha em 'fechado_ganho' garante uma nova
oportunidade aberta para o lead (recompra). Idempotente e fail-soft."""
import logging
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import create_deal

logger = logging.getLogger(__name__)

# ⚠️ O NOME PRECISA SER LITERALMENTE IGUAL AO DA LINHA EM `pipelines`.
#
# Incidente (medido em 09/09/2026): esta constante valia "Reposição - João" e o funil
# real se chama "João - Reposição" (id 79e35e6b-01d1-482a-bdf0-64c733ff1ca4). Como
# create_deal (leads/service.py:1131-1147) resolve o pipeline por `.eq("name", ...)` e,
# não achando, cai calado no fallback "primeiro pipeline por order_index" — e SEIS
# funis empatam em order_index = 0 — todo deal automático de reposição foi parar em
# "Valeria - Importação Leads Frios": 19 deals entre 07/08/2026 e 04/09/2026, um por
# venda fechada, cada um invisível para o João (a policy de visibilidade é por
# owner_user_id do funil).
#
# Nada estourou porque ensure_reposicao_deal é fail-soft por desenho e create_deal
# CRIOU o deal — só no lugar errado. É o motivo de este nome estar travado por teste
# contra o valor real (test_recuperacao_migration_2026_09_09.py): um typo aqui não
# produz erro nenhum, produz um funil silenciosamente errado.
REPOSICAO_PIPELINE_NAME = "João - Reposição"
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
