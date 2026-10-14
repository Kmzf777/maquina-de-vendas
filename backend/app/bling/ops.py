# backend/app/bling/ops.py
"""Operacoes manuais da sincronia de pedidos Bling, POR CONTA.

Roda DENTRO do container do worker (tem o env com as credenciais e o Redis da
trava). Mora em `app/` e nao em `scripts/` porque `scripts/` fica fora da imagem
(`backend/.dockerignore`). Ver docs/avaliacao/runbook-sync-bling.md para a ordem, os custos e as
conferencias antes/depois.

    python -m app.bling.ops backfill --conta default --desde 2026-07-23
    python -m app.bling.ops backfill --conta secundaria --meses 12 --estimar
    python -m app.bling.ops reprocessar-falhas --conta default
    python -m app.bling.ops varrer --conta secundaria
    python -m app.bling.ops reconciliar --conta default --dias 35

Todos os comandos sao idempotentes. A saida e um JSON com o resultado (sem
segredo nenhum: so contagens, datas e ids de pedido).
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import date


def _data(texto: str) -> date:
    return date.fromisoformat(texto)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.bling.ops", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)

    b = sub.add_parser("backfill", help="importa pedidos de um intervalo (retomavel)")
    b.add_argument("--conta", required=True)
    b.add_argument("--desde", type=_data, help="AAAA-MM-DD (inclusivo)")
    b.add_argument("--ate", type=_data, help="AAAA-MM-DD (inclusivo; padrao: hoje UTC)")
    b.add_argument("--meses", type=int, default=12,
                   help="usado so sem --desde (janela de 30*meses dias ate --ate)")
    b.add_argument("--reiniciar", action="store_true",
                   help="ignora o cursor salvo da conta e refaz o intervalo inteiro")
    b.add_argument("--estimar", action="store_true",
                   help="so lista e conta (custo de API sem gravar nada)")

    r = sub.add_parser("reprocessar-falhas",
                       help="devolve para a fila os eventos de webhook `failed` da conta")
    r.add_argument("--conta", required=True)
    v = sub.add_parser("varrer", help="uma rodada da varredura de pedidos alterados")
    v.add_argument("--conta", required=True)

    c = sub.add_parser("reconciliar",
                       help="confere Bling x banco por dia (ate ontem) e reimporta o divergente")
    c.add_argument("--conta", required=True)
    c.add_argument("--dias", type=int, default=None, help="padrao: 35")
    return p


async def _executar(args) -> dict:
    if args.comando == "backfill":
        from app.bling.backfill import run
        return await run(months=args.meses, account=args.conta, data_inicial=args.desde,
                         data_final=args.ate, reiniciar=args.reiniciar,
                         estimar=args.estimar)
    if args.comando == "reprocessar-falhas":
        from app.bling.webhook_processor import reabrir_falhas
        return {"conta": args.conta,
                "reabertos": await asyncio.to_thread(reabrir_falhas, args.conta)}
    if args.comando == "varrer":
        from app.bling.varredura import varrer_conta
        return await varrer_conta(args.conta)
    if args.comando == "reconciliar":
        from app.bling.reconciliacao import reconciliar_conta
        return await reconciliar_conta(args.conta, dias=args.dias)
    raise SystemExit(f"comando desconhecido: {args.comando}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    resultado = asyncio.run(_executar(args))
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
    return 1 if resultado.get("status") in ("interrompido", "ocupado", "erro", "parcial", "divergente") else 0


if __name__ == "__main__":
    sys.exit(main())
