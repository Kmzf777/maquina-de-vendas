# backend/app/conversions/types.py
"""Tipos compartilhados entre os clientes de plataforma e o sender."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SendResult:
    """Resultado de UM envio. `permanent` = não adianta tentar de novo (payload inválido,
    permissão) — o sender marca `erro` direto em vez de agendar retentativa."""
    ok: bool
    permanent: bool = False
    error: str | None = None
    response: dict[str, Any] | None = field(default=None)
