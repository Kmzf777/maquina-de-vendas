"""/api/agente-pedidos/* — consumido pelo bot do Discord (agente #pedidos).

Contrato: docs/superpowers/plans/2026-10-21-agente-pedidos.md (repositorio da
central). Toda rota exige `X-Agente-Token`. Erro sempre como
`{"erro", "mensagem"}` no TOPO do corpo, sem o envelope `{"detail": ...}` do
FastAPI — por isso a classe de rota `RotaAgente`, que converte o
`HTTPException(detail=dict)` e o erro de validacao do corpo (inclusive os da
dependencia de token) sem tocar no tratamento de erro do resto da API.
"""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from app.agente_pedidos import confirmar as conf
from app.agente_pedidos import contas, leitura, rascunhos
from app.agente_pedidos.auth import exigir_token
from app.agente_pedidos.erros import erro


def _texto_validacao(exc: RequestValidationError) -> str:
    partes = []
    for e in exc.errors():
        local = ".".join(str(p) for p in e.get("loc", ()) if p not in ("body", "query"))
        partes.append(f"{local}: {e.get('msg')}" if local else str(e.get("msg")))
    return "dados inválidos — " + "; ".join(partes)


class RotaAgente(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except HTTPException as exc:
                if isinstance(exc.detail, dict) and "erro" in exc.detail:
                    return JSONResponse(exc.detail, status_code=exc.status_code,
                                        headers=getattr(exc, "headers", None))
                raise
            except RequestValidationError as exc:
                return JSONResponse({"erro": "validacao", "mensagem": _texto_validacao(exc)},
                                    status_code=422)
        return handler


router = APIRouter(prefix="/api/agente-pedidos", tags=["agente-pedidos"],
                   dependencies=[Depends(exigir_token)], route_class=RotaAgente)


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
@router.get("/contas")
async def listar_contas():
    return contas.listar()


@router.get("/clientes")
async def buscar_clientes(conta: str = Query(...), q: str = Query("")):
    conta = contas.validar(conta)
    return await asyncio.to_thread(leitura.clientes, conta, q)


@router.get("/produtos")
async def buscar_produtos(conta: str = Query(...), q: str = Query("")):
    conta = contas.validar(conta)
    return await asyncio.to_thread(leitura.produtos, conta, q)


@router.get("/vendedores")
async def listar_vendedores(conta: str = Query(...)):
    conta = contas.validar(conta)
    return await asyncio.to_thread(leitura.vendedores, conta)


@router.get("/formas-pagamento")
async def listar_formas(conta: str = Query(...),
                        finalidade: Literal["venda", "compra"] = Query("venda")):
    conta = contas.validar(conta)
    return await asyncio.to_thread(leitura.formas_pagamento, conta, finalidade)


# --------------------------------------------------------------------------
# Rascunhos
# --------------------------------------------------------------------------
async def _guardar(r: dict) -> JSONResponse:
    salvo = await rascunhos.guardar(r)
    return JSONResponse(rascunhos.resposta(salvo), status_code=201)


@router.post("/rascunhos/venda", status_code=201)
async def rascunho_venda(corpo: rascunhos.RascunhoVendaIn):
    return await _guardar(await asyncio.to_thread(rascunhos.preparar_venda, corpo))


@router.post("/rascunhos/compra", status_code=201)
async def rascunho_compra(corpo: rascunhos.RascunhoCompraIn):
    return await _guardar(await rascunhos.preparar_compra(corpo))


@router.post("/rascunhos/contato", status_code=201)
async def rascunho_contato(corpo: rascunhos.RascunhoContatoIn):
    return await _guardar(await asyncio.to_thread(rascunhos.preparar_contato, corpo))


class ConfirmarIn(BaseModel):
    discord_id: str = Field(min_length=1)


@router.post("/rascunhos/{id_}/confirmar")
async def confirmar_rascunho(id_: str, corpo: ConfirmarIn):
    status, dados = await conf.confirmar(id_, corpo.discord_id)
    return JSONResponse(dados, status_code=status)


@router.get("/rascunhos/{id_}/resultado")
async def resultado_rascunho(id_: str):
    res = await conf.resultado(id_)
    if res is None:
        raise erro(410, "vencido", "rascunho inexistente ou vencido")
    return res


@router.delete("/rascunhos/{id_}", status_code=204)
async def cancelar_rascunho(id_: str):
    if not await conf.cancelar(id_):
        raise erro(410, "vencido", "rascunho inexistente ou vencido")
    return Response(status_code=204)
