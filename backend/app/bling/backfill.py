"""Importacao dos pedidos historicos (decisao D8: 12 meses).

Janelas de 30 dias por dois motivos: o filtro de periodo do Bling rejeita
intervalos maiores que 1 ano (HTTP 400), e janelas curtas tornam o job
retomavel — se cair no meio, recomeca da ultima janela concluida, nao do zero.

Custo: ~2 chamadas por pedido (listagem paginada + GET do detalhe, que e a
unica forma de obter os itens). Com 3 req/s, ~1,5 pedido por segundo.

MULTI-CONTA: `run()` aceita `account`, mas hoje so e chamado para a conta
default — o endpoint /backfill (router.py) nao expoe o parametro. Decisao 4 da
spec da segunda conta: paridade total dai pra frente (sync, webhook, emissao),
sem importar o historico antigo da conta 2. Mesmo assim a conta e passada de
ponta a ponta (cliente HTTP, espelho de contatos, projecao em `sales`) para o
parametro nao virar decorativo: se um dia alguem decidir rodar o backfill para
a conta 2 na mao, a funcao ja se comporta direito.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.bling import config
from app.bling.orders import upsert_from_bling
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_RESOURCE = "backfill"
_WINDOW_DAYS = 30


def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def build_windows(inicio: date, fim: date, dias: int = _WINDOW_DAYS) -> list[tuple[str, str]]:
    """Fatia [inicio, fim] em janelas contiguas de `dias`, sem lacuna nem sobreposicao."""
    janelas = []
    atual = inicio
    while atual <= fim:
        termino = min(atual + timedelta(days=dias - 1), fim)
        janelas.append((atual.isoformat(), termino.isoformat()))
        atual = termino + timedelta(days=1)
    return janelas


def _load_progress(account: str) -> str | None:
    res = (get_supabase().table("bling_sync_state").select("last_cursor")
           .eq("resource", _RESOURCE).eq("account", account)
           .limit(1).maybe_single().execute())
    return (getattr(res, "data", None) or {}).get("last_cursor")


def _save_progress(account: str, cursor: str) -> None:
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": _RESOURCE, "account": account, "last_cursor": cursor,
         "last_sync_at": datetime.now(timezone.utc).isoformat(),
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="account,resource").execute())


def _contact_row(account: str, contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("account", account).eq("id", contact_id)
           .limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _lead_for_contact(account: str, contact_id: int | None) -> str | None:
    if not contact_id:
        return None
    from app.bling.contacts import ensure_lead
    contato = await asyncio.to_thread(_contact_row, account, int(contact_id))
    return await ensure_lead(contato, account) if contato else None


async def run(months: int = 12, hoje: date | None = None,
              account: str = config.DEFAULT_ACCOUNT) -> dict:
    """Importa os pedidos dos ultimos `months` meses. Retomavel."""
    fim = hoje or datetime.now(timezone.utc).date()
    # -1: queremos `30 * months` DIAS de cobertura (contagem inclusiva). Sem o -1,
    # o intervalo [inicio, fim] tem 30*months + 1 dias e sobra 1 dia solto, gerando
    # uma janela extra de 1 dia toda vez (ex.: months=1 vira 2 janelas, nao 1).
    inicio = fim - timedelta(days=30 * months - 1)

    concluido_ate = await asyncio.to_thread(_load_progress, account)
    janelas = build_windows(inicio, fim)
    if concluido_ate:
        janelas = [j for j in janelas if j[0] > concluido_ate]
        logger.info("[BLING BACKFILL] retomando apos %s (%d janelas restantes)",
                    concluido_ate, len(janelas))

    total = 0
    async with _new_client(account) as client:
        for win_inicio, win_fim in janelas:
            params = {"dataInicial": win_inicio, "dataFinal": win_fim}
            ids = [int(p["id"]) async for p in client.paginate("/pedidos/vendas", params)]
            for order_id in ids:
                # A listagem nao traz itens; o detalhe e obrigatorio.
                pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}
                if not pedido:
                    continue
                contact_id = (pedido.get("contato") or {}).get("id")
                lead_id = await _lead_for_contact(account, contact_id)
                await upsert_from_bling(
                    pedido, lead_id=lead_id,
                    event_date=f"{pedido.get('data')}T00:00:00+00:00",
                    account=account,
                )
                total += 1
            await asyncio.to_thread(_save_progress, account, win_fim)
            logger.info("[BLING BACKFILL] janela %s..%s: %d pedidos (total %d)",
                        win_inicio, win_fim, len(ids), total)

    return {"pedidos": total, "janelas": len(janelas)}
