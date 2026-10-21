"""Erro do agente de pedidos: corpo `{"erro", "mensagem"}` no topo da resposta.

`HTTPException` com `detail` dict; o router (`router.RotaAgente`) devolve o
`detail` como corpo, sem o envelope `{"detail": ...}` do FastAPI.
"""
from fastapi import HTTPException


def erro(status: int, codigo: str, mensagem: str, **extra) -> HTTPException:
    return HTTPException(status, {"erro": codigo, "mensagem": mensagem, **extra})
