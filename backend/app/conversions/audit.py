# backend/app/conversions/audit.py
"""Checagem: no máximo um evento por lead × etapa × plataforma (venda: por venda), e nenhum
`event_id` repetido na mesma plataforma. Puro, sem I/O — a CLI é `scripts/conversoes/checar_duplicatas`.

Linhas `ignorado` e `fora_da_janela` nunca saíram para a plataforma: não contam."""
from collections import defaultdict
from typing import Any

_NUNCA_ENVIADAS = ("ignorado", "fora_da_janela")


def _grupos(rows, key_fn) -> list[dict[str, Any]]:
    g: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is not None:
            g[k].append(r)
    return [{"key": k, "n": len(v), "rows": [{"id": r.get("id"), "status": r.get("status")} for r in v]}
            for k, v in sorted(g.items(), key=lambda kv: tuple(str(x) for x in kv[0])) if len(v) > 1]


def find_duplicates(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    vivas = [r for r in rows if r.get("status") not in _NUNCA_ENVIADAS]
    return {
        "lead_stage": _grupos(vivas, lambda r: None if r.get("stage") == "purchase"
                              else (r.get("platform"), r.get("stage"), r.get("lead_id"))),
        "sale": _grupos(vivas, lambda r: (r.get("platform"), r.get("sale_id"))
                        if r.get("stage") == "purchase" and r.get("sale_id") else None),
        "event_id": _grupos(vivas, lambda r: (r.get("platform"), r.get("event_id")) if r.get("event_id") else None),
    }
