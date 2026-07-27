"""Divide o lote de resgate 20260727 em dois dias — capacidade de atendimento do vendedor.

O reagendamento de 27/07 criou 178 `handoff_rescue` pending para 28/07 09:00. São 178
conversas potencialmente abrindo de uma vez para UMA pessoa (o João) numa única manhã;
mais do que ele consegue atender, o que anularia o objetivo do resgate — o lead responde
e fica sem resposta de novo.

Este script move a metade MAIS ANTIGA para o dia seguinte. O critério é `metadata.
original_handoff_at`: os handoffs mais recentes vão primeiro (contexto ainda fresco na
cabeça do lead, maior chance de conversão), os mais antigos ficam para o 2º dia.

Idempotente: reprocessar não move nada de novo, porque a seleção é sempre "jobs do batch
com fire_at == --from-at", e após o UPDATE metade já está em --to-at.

DRY-RUN por padrão. Só `--execute --yes` grava.

USO
---
    python -m scripts.split_handoff_rescue_batch_2026_07_27
    python -m scripts.split_handoff_rescue_batch_2026_07_27 --execute --yes
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

from supabase import create_client

BATCH_TAG = "handoff_rescue_recovery_20260727"
DEFAULT_FROM = "2026-07-28T12:00:00Z"  # terça 09:00 BRT
DEFAULT_TO = "2026-07-29T12:00:00Z"    # quarta 09:00 BRT
_BRT = timezone(timedelta(hours=-3))


def _sb():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-at", default=DEFAULT_FROM)
    p.add_argument("--to-at", default=DEFAULT_TO)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--yes", action="store_true")
    args = p.parse_args()

    sb = _sb()
    rows = (sb.table("follow_up_jobs")
            .select("id, lead_id, fire_at, metadata")
            .eq("job_type", "handoff_rescue").eq("status", "pending")
            .execute().data or [])
    lote = [
        r for r in rows
        if (r.get("metadata") or {}).get("recovery_batch") == BATCH_TAG
        and r["fire_at"].startswith(args.from_at[:13])
    ]
    if not lote:
        print(f"Nenhum job do batch {BATCH_TAG} em {args.from_at}. Nada a fazer.")
        return

    # Mais recentes primeiro; a metade final (mais antiga) é a que se move.
    lote.sort(key=lambda r: (r.get("metadata") or {}).get("original_handoff_at") or "",
              reverse=True)
    metade = len(lote) // 2
    fica, move = lote[:len(lote) - metade], lote[len(lote) - metade:]

    d_from = datetime.fromisoformat(args.from_at.replace("Z", "+00:00")).astimezone(_BRT)
    d_to = datetime.fromisoformat(args.to_at.replace("Z", "+00:00")).astimezone(_BRT)

    print(f"batch: {BATCH_TAG}  |  total pending em {d_from:%d/%m %H:%M} BRT: {len(lote)}")
    print(f"  fica em {d_from:%d/%m %H:%M} BRT : {len(fica)}  (handoffs mais recentes)")
    print(f"  move p/ {d_to:%d/%m %H:%M} BRT : {len(move)}  (handoffs mais antigos)")
    if fica:
        print(f"    corte: handoffs de {(fica[-1].get('metadata') or {}).get('original_handoff_at','?')[:16]} em diante ficam no 1º dia")
    print("-" * 74)

    if not (args.execute and args.yes):
        print("DRY-RUN — nada gravado. Use --execute --yes.")
        return

    movidos = 0
    for r in move:
        try:
            sb.table("follow_up_jobs").update({"fire_at": args.to_at}).eq("id", r["id"]).execute()
            movidos += 1
        except Exception as exc:
            print(f"  FALHA ao mover job {r['id']}: {exc}")
    print(f"{movidos} job(s) movido(s) para {d_to:%d/%m %H:%M} BRT.")


if __name__ == "__main__":
    main()
