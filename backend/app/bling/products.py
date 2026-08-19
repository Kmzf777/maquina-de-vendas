"""Espelho local do catalogo de produtos do Bling.

Por que espelho e nao consulta ao vivo: o combobox do modal de venda dispara uma
busca a cada tecla. Consultar o Bling ali queimaria o orcamento de 3 req/s da
CONTA INTEIRA — o job de sync e o processamento de webhook ficariam sem vaga.
O espelho tambem torna o modal instantaneo e imune a instabilidade do Bling.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_RESOURCE = "products"
# criterio=5 => "Todos". Inclui inativos de proposito: pedido antigo e backfill
# precisam do produto no espelho para resolver descricao e SKU.
_CRITERIO_TODOS = 5


def map_product(bruto: dict) -> dict:
    """Traduz o objeto do Bling para a linha de `bling_products`."""
    pai = bruto.get("idProdutoPai")
    estoque = bruto.get("estoque") or {}
    return {
        "id": int(bruto["id"]),
        "codigo": bruto.get("codigo") or None,
        "nome": bruto.get("nome") or "",
        "preco": bruto.get("preco"),
        "unidade": bruto.get("unidade") or None,
        "tipo": bruto.get("tipo") or None,
        "formato": bruto.get("formato") or None,
        "situacao": bruto.get("situacao") or None,
        # O Bling manda 0 para "sem pai"; 0 nao e um id valido.
        "id_produto_pai": int(pai) if pai else None,
        "saldo_virtual": estoque.get("saldoVirtualTotal"),
        "imagem_url": bruto.get("imagemURL") or None,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_sync_state(resource: str) -> dict | None:
    res = (get_supabase().table("bling_sync_state")
           .select("*").eq("resource", resource).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _save_sync_state(resource: str, *, last_sync_at: str, cursor: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": resource, "last_sync_at": last_sync_at,
         "last_cursor": cursor, "updated_at": now},
        on_conflict="resource").execute())


async def _upsert(rows: list[dict]) -> None:
    if not rows:
        return
    await asyncio.to_thread(
        lambda: get_supabase().table("bling_products")
        .upsert(rows, on_conflict="id").execute()
    )


async def sync_products(client, *, full: bool = False, batch_size: int = 200) -> int:
    """Sincroniza o catalogo. `full=True` traz tudo; senao, so o que mudou.

    Sem estado anterior, cai para completo — e o primeiro sync.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    params: dict = {}
    if not full:
        estado = await asyncio.to_thread(_load_sync_state, _RESOURCE)
        desde = (estado or {}).get("last_sync_at")
        if desde:
            params["dataAlteracaoInicial"] = desde
        else:
            full = True
    if full:
        params["criterio"] = _CRITERIO_TODOS

    total, buffer = 0, []
    async for bruto in client.paginate("/produtos", params):
        buffer.append(map_product(bruto))
        if len(buffer) >= batch_size:
            await _upsert(buffer)
            total += len(buffer)
            buffer = []
    if buffer:
        await _upsert(buffer)
        total += len(buffer)

    await asyncio.to_thread(_save_sync_state, _RESOURCE, last_sync_at=started_at)
    logger.info("[BLING] catalogo sincronizado: %d produtos (full=%s)", total, full)
    return total


async def apply_product_event(event: str, payload: dict) -> None:
    """Aplica um webhook `product.*` no espelho."""
    if event.endswith(".deleted"):
        row = {
            "id": int(payload["id"]),
            "situacao": "I",  # nunca apaga: pedidos historicos referenciam o produto
            "nome": payload.get("nome") or "(removido)",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        row = map_product(payload)
    await _upsert([row])
