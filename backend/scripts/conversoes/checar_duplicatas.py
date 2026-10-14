"""Relatório de duplicatas em `ad_conversions` (só leitura).

Uso (de dentro do container da API/worker, em /app):
    python -m scripts.conversoes.checar_duplicatas
Sai com 1 se houver duplicata."""
import sys
from collections import Counter
from typing import Any

from app.conversions.audit import find_duplicates

_TITULOS = {"lead_stage": "lead × etapa × plataforma", "sale": "venda × plataforma",
            "event_id": "event_id × plataforma"}


def _ler() -> list[dict[str, Any]]:
    from app.db.paginacao import paginar
    from app.db.supabase import get_supabase
    sb = get_supabase()
    return paginar(lambda: sb.table("ad_conversions")
                   .select("id,lead_id,platform,stage,event_id,sale_id,status").order("id"))


def main(argv: list[str] | None = None) -> int:
    rows = _ler()
    print(f"ad_conversions: {len(rows)} linhas")
    for (p, s, st), n in sorted(Counter((r["platform"], r["stage"], r["status"]) for r in rows).items()):
        print(f"  {p:7} {s:12} {st:15} {n}")
    dup = find_duplicates(rows)
    total = sum(len(v) for v in dup.values())
    if not total:
        print("0 duplicatas (lead × etapa × plataforma, venda, event_id)")
        return 0
    print(f"{total} grupos duplicados:")
    for tipo, grupos in dup.items():
        for g in grupos:
            print(f"  [{_TITULOS[tipo]}] {g['key']}: {g['n']} linhas {g['rows']}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
