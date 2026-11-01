"""E-mail e endereço dos contatos do Bling para os públicos (cartão 4e0494e0).

A listagem do Bling não traz e-mail de nota nem endereço; só o GET /contatos/{id}. Guarda em
`audience_contact_details` e só busca de novo depois de `max_idade_dias`.
O Bling aqui é SÓ LEITURA: nenhum método além de `get`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from app.audiences.types import Detalhe

logger = logging.getLogger(__name__)


def _limpo(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _detalhe(data: dict[str, Any]) -> Detalhe:
    geral = ((data.get("endereco") or {}).get("geral") or {})
    return Detalhe(
        email=_limpo(data.get("email")) or _limpo(data.get("emailNotaFiscal")),
        municipio=_limpo(geral.get("municipio")),
        uf=_limpo(geral.get("uf")),
        cep=_limpo(geral.get("cep")),
    )


def _default_factory(conta: str):
    from app.bling.client import BlingClient
    return BlingClient(account=conta)


async def atualizar_detalhes(chaves: list[tuple[str, int]], store, *, agora: datetime,
                             client_factory: Callable[[str], Any] | None = None,
                             max_idade_dias: int = 30) -> dict[tuple[str, int], Detalhe]:
    chaves = list(dict.fromkeys((c, int(i)) for c, i in chaves))
    cache = store.detalhes(chaves) if chaves else {}
    limite = agora - timedelta(days=max_idade_dias)
    out: dict[tuple[str, int], Detalhe] = {}
    buscar: dict[str, list[int]] = {}
    for chave in chaves:
        em_cache = cache.get(chave)
        if em_cache and em_cache[1] >= limite:
            out[chave] = em_cache[0]
        else:
            buscar.setdefault(chave[0], []).append(chave[1])

    factory = client_factory or _default_factory
    novos: list[dict] = []
    for conta, ids in buscar.items():
        async with factory(conta) as client:
            for cid in ids:
                try:
                    resp = await client.get(f"/contatos/{cid}")
                    d = _detalhe((resp or {}).get("data") or {})
                except Exception as exc:  # noqa: BLE001 — um contato ruim não para a rodada
                    logger.warning("audiences: falha ao ler contato %s/%s do Bling: %s", conta, cid, exc)
                    em_cache = cache.get((conta, cid))
                    if em_cache:  # vencido, mas melhor que nada
                        out[(conta, cid)] = em_cache[0]
                    continue
                out[(conta, cid)] = d
                novos.append({"account": conta, "bling_contact_id": cid, "email": d.email,
                              "municipio": d.municipio, "uf": d.uf, "cep": d.cep,
                              "buscado_em": agora.isoformat()})
    if novos:
        store.salvar_detalhes(novos)
    return out
