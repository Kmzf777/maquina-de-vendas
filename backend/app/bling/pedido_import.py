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
from app.bling.orders import (
    PedidoSemLead,
    _sold_at_iso,
    garantir_reposicao_apos_venda,
    upsert_from_bling,
    venda_recente,
)
from app.bling.sync import map_contact
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Falhas PERMANENTES de um pedido: repetir nao conserta (pedido sem lead porque o
# contato nao existe/nao tem id; 4xx de validacao do Bling). Varredura e backfill
# registram e SEGUEM, sem segurar o cursor — um pedido envenenado nao pode
# congelar a conta. Transitorio (429, 5xx, timeout, token, teto diario) continua
# parando, e erro desconhecido continua segurando o cursor (pode ser o banco fora).
PERMANENTES = (PedidoSemLead, BlingValidationError)


def registrar_ignorados(alertar, account: str, origem: str, ignorados: list[dict]) -> None:
    """Registro duravel dos pedidos pulados por falha permanente: um alerta
    `bling_pedido_ignorado` em `system_alerts` com conta, origem e os ids em
    `metadata.pedidos`. O dedup e pelo CONJUNTO de pedidos (`chave`), entao o
    mesmo lote nao vira banner novo a cada rodada, mas um pedido novo envenenado
    gera o seu. `alertar` vem do chamador (cada modulo tem o seu, para os testes)."""
    ids = sorted({int(i["pedido"]) for i in ignorados})
    alertar("bling_pedido_ignorado", account,
            f"Pedidos Bling ignorados por falha permanente ({config.account(account).label})",
            f"{len(ids)} pedido(s) nao entraram ({origem}) e nao seguram mais o cursor: "
            f"{', '.join(str(i) for i in ids[:20])}. Corrigir a causa (contato/lead, "
            "dado do pedido) e reimportar; a reconciliacao diaria continua apontando.",
            metadata={"origem": origem, "pedidos": ignorados[:50]},
            chave=f"{origem}:{','.join(str(i) for i in ids[:50])}",
            dedup_horas=24 * 7)


def _venda_ja_existia(account: str, order_id: int) -> bool:
    """Ja ha linha em `sales` para este pedido? Erro de leitura -> True (nao cria
    card), a mesma regra fail-closed do webhook."""
    try:
        res = (get_supabase().table("sales").select("id")
               .eq("bling_account", account).eq("bling_order_id", order_id)
               .limit(1).execute())
        return bool(getattr(res, "data", None))
    except Exception:  # noqa: BLE001
        logger.warning("[BLING] nao consegui checar se o pedido %s ja existia — "
                       "Reposicao nao sera criada", order_id, exc_info=True)
        return True


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
                          event_date: str | None = None, *,
                          pos_venda: bool = False) -> dict | None:
    """Detalhe (a listagem nao traz itens) + lead + upsert. Devolve o pedido.

    `event_date` padrao = a data do pedido a meia-noite, o que o backfill
    sempre usou: um webhook mais novo do mesmo pedido continua vencendo.

    `pos_venda=True` (so a varredura): venda NOVA e RECENTE (7 dias, a mesma
    guarda do webhook) abre a Reposicao como o webhook abriria — a varredura
    existe justamente para o pedido cujo webhook se perdeu. Backfill e
    reconciliacao nao passam isso: nunca abrem cards em massa.
    """
    conta = config.account(account).key
    pedido = (await client.get(f"/pedidos/vendas/{int(order_id)}")).get("data") or {}
    if not pedido:
        return None
    lead_id = await lead_do_pedido(client, conta, pedido)
    event_date = event_date or f"{pedido.get('data')}T00:00:00+00:00"

    nova_e_recente = False
    if pos_venda and lead_id and venda_recente(_sold_at_iso(pedido, event_date)):
        nova_e_recente = not await asyncio.to_thread(_venda_ja_existia, conta, int(order_id))

    await upsert_from_bling(pedido, lead_id=lead_id, event_date=event_date, account=conta)

    if nova_e_recente:
        try:
            await asyncio.to_thread(garantir_reposicao_apos_venda, lead_id, None)
        except Exception:  # noqa: BLE001 — a venda ja esta gravada
            logger.exception("[BLING] Reposicao do lead %s falhou (venda mantida)", lead_id)
    return pedido
