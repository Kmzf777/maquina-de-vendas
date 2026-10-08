# backend/app/conversions/types.py
"""Tipos compartilhados entre os clientes de plataforma e o sender."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SendResult:
    """Resultado de UM envio. `permanent` = não adianta tentar de novo sem mudar o payload
    (4xx de validação) — o sender marca `erro` direto em vez de agendar retentativa.

    NÃO são permanentes (entram no backoff): token inválido/vencido e permissão negada (HTTP
    401/403; na Meta também os códigos OAuth/permissão), limite de taxa, 5xx, erro de rede e
    variável de ambiente faltando — tudo isso se resolve sem mexer na linha."""
    ok: bool
    permanent: bool = False
    error: str | None = None
    response: dict[str, Any] | None = field(default=None)
