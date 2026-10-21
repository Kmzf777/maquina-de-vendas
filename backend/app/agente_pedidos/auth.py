"""Token do agente de pedidos (bot do Discord). Comparação em tempo constante."""
import hmac
from typing import Annotated

from fastapi import Header

from app.agente_pedidos.erros import erro
from app.config import settings


def exigir_token(x_agente_token: Annotated[str | None, Header()] = None) -> None:
    esperado = getattr(settings, "agente_pedidos_token", None)
    if not esperado:
        raise erro(503, "nao_configurado", "agente de pedidos desligado no backend")
    if not x_agente_token or not hmac.compare_digest(
            x_agente_token.encode("utf-8"), esperado.encode("utf-8")):
        raise erro(401, "token", "token inválido")
