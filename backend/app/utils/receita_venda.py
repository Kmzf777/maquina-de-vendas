"""D7 (cartao 1e6381fe): receita = valor - frete, so de venda nao cancelada.

Espelho de frontend/src/lib/sales/receita.ts. O frete fica a parte.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

_CENTAVO = Decimal("0.01")


def _dec(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor if valor is not None else 0))
    except Exception:  # noqa: BLE001 — valor sujo conta como zero
        return Decimal("0")


def venda_cancelada(sale: Mapping[str, Any]) -> bool:
    return str(sale.get("status") or "").strip().lower().startswith("cancel")


def receita_da_venda(sale: Mapping[str, Any]) -> float:
    if venda_cancelada(sale):
        return 0.0
    liquido = _dec(sale.get("value")) - _dec(sale.get("freight"))
    return float(liquido.quantize(_CENTAVO, rounding=ROUND_HALF_UP))


def frete_da_venda(sale: Mapping[str, Any]) -> float:
    if venda_cancelada(sale):
        return 0.0
    return float(_dec(sale.get("freight")).quantize(_CENTAVO, rounding=ROUND_HALF_UP))
