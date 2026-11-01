"""CLI manual: `python -m app.audiences [--dry-run]`. Ignora AUDIENCE_SYNC_ENABLED."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.audiences.service import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.audiences",
                                     description="Sincroniza os públicos PL/Atacado no Meta e no Google.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Meta só confere o público; Google valida sem gravar.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    resumo = asyncio.run(run(trigger="manual", dry_run=args.dry_run))
    print(json.dumps(resumo, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
