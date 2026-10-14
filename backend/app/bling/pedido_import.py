"""Importar UM pedido do Bling para `sales`, do jeito certo, em qualquer caminho
(webhook, backfill, varredura, reconciliacao).

O PROBLEMA (G2 da avaliacao 2026-10-13): o lead da venda vem do contato, e o
contato vinha so do espelho `bling_contacts`, que e atualizado UMA vez por dia
(nao existe webhook de contato). Pedido de cliente cadastrado no mesmo dia
virava `lead_id` nulo -> 23502 no Postgres -> evento `failed` para sempre.

A SOLUCAO: contato fora do espelho e buscado na hora (`GET /contatos/{id}`) pelo
`BlingClient` DA CONTA — o mesmo cliente que o chamador ja abriu, entao a
chamada extra entra no mesmo orcamento de 3 req/s e no mesmo token (nenhum
refresher novo) — e gravado no espelho antes do `ensure_lead`. O detalhe do
contato ainda traz `vendedor.id`, que a listagem diaria nao traz: e o que faz o
segundo degrau da cascata de vendedor (D8) funcionar para cliente novo.
"""
import asyncio
import logging

from app.bling import config
from app.bling.contacts import ensure_lead
from app.bling.errors import BlingValidationError
from app.bling.orders import upsert_from_bling
from app.bling.sync import map_contact
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _contato_do_espelho(account: str, contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("account", account).eq("id", contact_id)
           .limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _gravar_no_espelho(linha: dict) -> None:
    (get_supabase().table("bling_contacts")
     .upsert(linha, on_conflict="account,id").execute())


async def buscar_contato(client, account: str, contact_id: int) -> dict | None:
    """`GET /contatos/{id}` e grava no espelho da conta. Devolve a linha do espelho.

    Contato que nao existe (4xx de validacao, ex.: 404) devolve None. Erro
    transitorio (429, 5xx, teto diario, token) SOBE: quem chamou decide (o
    webhook reagenda o evento; o backfill para).
    """
    try:
        bruto = (await client.get(f"/contatos/{int(contact_id)}")).get("data") or {}
    except BlingValidationError as exc:
        logger.warning("[BLING] contato %s nao encontrado na conta %s: %s",
                       contact_id, account, exc)
        return None
    if not bruto.get("id"):
        return None
    linha = {**map_contact(bruto), "account": account}
    await asyncio.to_thread(_gravar_no_espelho, linha)
    logger.info("[BLING] contato %s buscado sob demanda (conta %s)", contact_id, account)
    return linha


async def contato_do_pedido(client, account: str, contact_id: int) -> dict | None:
    contato = await asyncio.to_thread(_contato_do_espelho, account, int(contact_id))
    if contato:
        return contato
    return await buscar_contato(client, account, int(contact_id))


async def lead_do_pedido(client, account: str, pedido: dict) -> str | None:
    """Lead dono do pedido NESTA conta (cria se preciso, decisao D6)."""
    contact_id = (pedido.get("contato") or {}).get("id")
    if not contact_id:
        return None
    contato = await contato_do_pedido(client, account, int(contact_id))
    if not contato:
        return None
    return await ensure_lead(contato, account)


async def importar_pedido(client, account: str, order_id: int,
                          event_date: str | None = None) -> dict | None:
    """Detalhe (a listagem nao traz itens) + lead + upsert. Devolve o pedido.

    `event_date` padrao = a data do pedido a meia-noite, o que o backfill
    sempre usou: um webhook mais novo do mesmo pedido continua vencendo.
    """
    conta = config.account(account).key
    pedido = (await client.get(f"/pedidos/vendas/{int(order_id)}")).get("data") or {}
    if not pedido:
        return None
    lead_id = await lead_do_pedido(client, conta, pedido)
    await upsert_from_bling(
        pedido, lead_id=lead_id,
        event_date=event_date or f"{pedido.get('data')}T00:00:00+00:00",
        account=conta,
    )
    return pedido
