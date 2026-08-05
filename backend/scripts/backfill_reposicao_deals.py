# backend/scripts/backfill_reposicao_deals.py
"""Backfill do ciclo de reposição: para todo lead com >=1 deal 'fechado_ganho' e SEM deal
aberto, cria uma oportunidade de reposição. Idempotente (ensure_reposicao_deal usa
create_deal(dedupe_open=True)); pode rodar 2x sem duplicar.

Uso: python -m scripts.backfill_reposicao_deals   (a partir de backend/)
"""
import logging

from app.db.supabase import get_supabase
from app.leads.service import get_open_deal
from app.leads.reposicao import ensure_reposicao_deal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_reposicao")


def main() -> None:
    sb = get_supabase()
    won_stage_ids = [s["id"] for s in (
        sb.table("pipeline_stages").select("id").eq("key", "fechado_ganho").execute().data or []
    )]
    if not won_stage_ids:
        logger.info("Nenhum stage 'fechado_ganho' — nada a fazer.")
        return

    won_deals = (
        sb.table("deals").select("lead_id").in_("stage_id", won_stage_ids).execute().data or []
    )
    lead_ids = sorted({d["lead_id"] for d in won_deals if d.get("lead_id")})
    logger.info("Leads com fechado_ganho: %d", len(lead_ids))

    created = 0
    for lead_id in lead_ids:
        try:
            if get_open_deal(lead_id):
                continue  # já tem oportunidade aberta
            ensure_reposicao_deal(lead_id)
            created += 1
        except Exception as exc:
            logger.error("backfill: lead %s falhou: %s", lead_id, exc)
    logger.info("Backfill concluído — oportunidades de reposição criadas: %d", created)


if __name__ == "__main__":
    main()
