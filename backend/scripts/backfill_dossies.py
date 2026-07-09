"""Backfill do Dossiê do Lead (Onda 2, 09/07/2026).

Consolida a memória de longo prazo dos leads que conversaram mas ficaram com
`rolling_summary` NULL — tanto vítimas do burn de 08/07 (1.366 gerações que falharam
no parse e avançaram a marca d'água sem persistir nada) quanto a base histórica
anterior à Camada de Memória. Usa exatamente o caminho de produção
(`refresh_lead_memory`, que desde a Onda 2 lê o histórico completo capado quando não
há dossiê prévio) — lock, fail-soft e token tracking inclusos.

Uso (de backend/, com o .env do ambiente-alvo carregado):
    python -m scripts.backfill_dossies --limit 60 [--dry-run] [--sleep 2.0]

Seleção: leads sem rolling_summary, com last_customer_message_at preenchido (já
conversaram), dos mais recentes para os mais antigos (valor comercial primeiro).
"""
import argparse
import asyncio
import logging
import sys

from app.db.supabase import get_supabase
from app.agent.memory_manager import refresh_lead_memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_dossies")


def _select_candidates(limit: int) -> list[dict]:
    res = (
        get_supabase().table("leads")
        .select("id, name, phone, last_customer_message_at")
        .is_("rolling_summary", "null")
        .not_.is_("last_customer_message_at", "null")
        .order("last_customer_message_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data if isinstance(res.data, list) else []


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="máximo de leads neste run")
    parser.add_argument("--sleep", type=float, default=2.0, help="pausa entre leads (rate limit)")
    parser.add_argument("--dry-run", action="store_true", help="só lista os candidatos")
    args = parser.parse_args()

    candidates = _select_candidates(args.limit)
    logger.info("%d lead(s) candidatos a backfill (limit=%d)", len(candidates), args.limit)
    if args.dry_run:
        for c in candidates:
            logger.info("dry-run: %s (%s) last_msg=%s", c.get("name"), c.get("phone"),
                        c.get("last_customer_message_at"))
        return 0

    done = 0
    for i, c in enumerate(candidates, 1):
        lead_id = c["id"]
        try:
            ok = await refresh_lead_memory(lead_id)
            done += 1 if ok else 0
            logger.info("[%d/%d] lead %s (%s): %s", i, len(candidates), c.get("name"),
                        c.get("phone"), "dossiê gravado" if ok else "sem delta/sem mudança")
        except Exception as exc:  # refresh é fail-soft; guarda extra
            logger.error("[%d/%d] lead %s falhou: %s", i, len(candidates), lead_id, exc)
        await asyncio.sleep(args.sleep)

    logger.info("backfill concluído: %d dossiê(s) gravados de %d candidatos", done, len(candidates))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
