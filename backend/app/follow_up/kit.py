"""O que é "kit de degustação" para o follow-up do João (spec 2026-10-06, P6.2). PURO.

Kit = algum item da venda com `bling_product_id` na lista de SKUs de kit das DUAS contas
Bling, OU com "kit degust" na descrição (sem acento, sem caixa, espaços colapsados). A
descrição cobre o item lançado à mão no CRM (sem SKU) e o SKU novo que ninguém lembrou de
pôr aqui. "Kit Café Filtrado Drip…" existe em produção e NÃO é kit de degustação — por
isso o trecho é "kit degust", e não "kit".
"""
from __future__ import annotations

import unicodedata
from typing import Any, Iterable, Mapping

# SKUs medidos em `sale_items` de produção em 06/10/2026, por conta Bling.
SKUS_KIT: Mapping[str, frozenset[int]] = {
    "default": frozenset({16536419853, 16637692216, 16658150270, 9256328993}),
    "secundaria": frozenset({16697411791, 16701798396}),
}
SKUS_KIT_TODOS: frozenset[int] = frozenset().union(*SKUS_KIT.values())

_TRECHO_KIT = "kit degust"


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _sku(valor: Any) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def item_e_kit(item: Mapping[str, Any]) -> bool:
    """Este item de venda é kit de degustação?"""
    if _sku(item.get("bling_product_id")) in SKUS_KIT_TODOS:
        return True
    return _TRECHO_KIT in _normalizar(str(item.get("descricao") or ""))


def venda_e_kit(itens: Iterable[Mapping[str, Any]] | None) -> bool:
    """A venda tem ALGUM item de kit? Venda sem itens não é kit."""
    return any(item_e_kit(item) for item in (itens or ()))
