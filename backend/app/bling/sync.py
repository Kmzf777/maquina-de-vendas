"""Espelhos de contatos, formas de pagamento e vendedores + tick diario.

Contatos precisam de POLLING: a lista de recursos de webhook do Bling e
`order`, `product`, `stock`, `virtual_stock`, `product_supplier`, `invoice` e
`consumer_invoice` — nao existe webhook de contato.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.bling import config
from app.bling.products import sync_products
from app.db.supabase import get_supabase
from app.leads.service import normalize_phone

logger = logging.getLogger(__name__)

# criterio=1 => "Todos". O default da API e 3 ("ultimos incluidos"), que no
# primeiro sync deixaria a base incompleta sem avisar.
_CRITERIO_TODOS = 1


def _digits(value: str | None) -> str | None:
    if not value:
        return None
    out = "".join(ch for ch in value if ch.isdigit())
    return out or None


def _to_e164_br(raw: str | None) -> str | None:
    """Normaliza um telefone cru do Bling para o MESMO formato de `leads.phone`.

    O Bling guarda telefone em formato local, sem DDI (ex.: "(51) 99269-6163" ou
    "51 3714-1000"). `leads.phone` e sempre E.164 com o 55 do Brasil. Por isso
    chamamos `normalize_phone` (a mesma funcao que normaliza `leads.phone`) no
    valor cru primeiro — ela limpa a formatacao e resolve o 9o digito faltante
    em celulares — e SO DEPOIS prefixamos o "55". Prefixar antes quebraria fixo:
    um numero de 10 digitos (DDD+8) viraria 12 apos o 55, disparando por engano
    a insercao do 9o digito que `normalize_phone` reserva para celular.
    """
    limpo = normalize_phone(raw)
    return f"55{limpo}" if limpo else None


def map_contact(bruto: dict) -> dict:
    """Traduz o contato do Bling para `bling_contacts`, ja normalizado.

    `telefone_e164`/`celular_e164` usam `app.leads.service.normalize_phone` — a
    MESMA funcao que normaliza `leads.phone`. E isso que faz os dois lados
    casarem; o formato de texto livre do Bling nunca casaria sozinho.
    """
    endereco = ((bruto.get("endereco") or {}).get("geral")) or None
    financeiro = bruto.get("financeiro") or {}
    vendedor = bruto.get("vendedor") or {}
    return {
        "id": int(bruto["id"]),
        "nome": bruto.get("nome") or "",
        "fantasia": bruto.get("fantasia") or None,
        "tipo": bruto.get("tipo") or None,
        "doc_digits": _digits(bruto.get("numeroDocumento")),
        "telefone_e164": _to_e164_br(bruto.get("telefone")),
        "celular_e164": _to_e164_br(bruto.get("celular")),
        "email": (bruto.get("email") or "").strip() or None,
        "situacao": bruto.get("situacao") or None,
        "endereco": endereco,
        "vendedor_id": int(vendedor["id"]) if vendedor.get("id") else None,
        "condicao_pagamento": financeiro.get("condicaoPagamento") or None,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_sync_state(resource: str) -> dict | None:
    res = (get_supabase().table("bling_sync_state")
           .select("*").eq("resource", resource).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _save_sync_state(resource: str, *, last_sync_at: str, cursor: str | None = None) -> None:
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": resource, "last_sync_at": last_sync_at, "last_cursor": cursor,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="resource").execute())


async def _upsert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    await asyncio.to_thread(
        lambda: get_supabase().table(table).upsert(rows, on_conflict="id").execute()
    )


async def sync_contacts(client, *, batch_size: int = 200) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    estado = await asyncio.to_thread(_load_sync_state, "contacts")
    desde = (estado or {}).get("last_sync_at")
    params = {"dataAlteracaoInicial": desde} if desde else {"criterio": _CRITERIO_TODOS}

    total, buffer = 0, []
    async for bruto in client.paginate("/contatos", params):
        buffer.append(map_contact(bruto))
        if len(buffer) >= batch_size:
            await _upsert("bling_contacts", buffer)
            total += len(buffer)
            buffer = []
    if buffer:
        await _upsert("bling_contacts", buffer)
        total += len(buffer)

    await asyncio.to_thread(_save_sync_state, "contacts", last_sync_at=started_at)
    logger.info("[BLING] contatos sincronizados: %d", total)
    return total


async def sync_payment_methods(client) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    async for b in client.paginate("/formas-pagamentos", {}):
        rows.append({
            "id": int(b["id"]),
            "descricao": b.get("descricao") or "",
            "tipo_pagamento": b.get("tipoPagamento"),
            "situacao": b.get("situacao"),
            "padrao": b.get("padrao"),
            "finalidade": b.get("finalidade"),
            "synced_at": started_at,
        })
    await _upsert("bling_payment_methods", rows)
    await asyncio.to_thread(_save_sync_state, "payment_methods", last_sync_at=started_at)
    return len(rows)


async def sync_sellers(client) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    async for b in client.paginate("/vendedores", {}):
        # O nome do vendedor vem aninhado em `contato` na API de vendedores.
        nome = (b.get("contato") or {}).get("nome") or b.get("nome") or ""
        rows.append({
            "id": int(b["id"]),
            "nome": nome,
            "situacao": b.get("situacao"),
            "synced_at": started_at,
        })
    await _upsert("bling_sellers", rows)
    await asyncio.to_thread(_save_sync_state, "sellers", last_sync_at=started_at)
    return len(rows)


async def sync_all(*, full: bool = False) -> dict:
    """Roda os quatro syncs em sequencia (nunca em paralelo: 3 req/s e da conta)."""
    from app.bling.client import BlingClient

    async with BlingClient() as client:
        produtos = await sync_products(client, full=full)
        contatos = await sync_contacts(client)
        formas = await sync_payment_methods(client)
        vendedores = await sync_sellers(client)
    return {"produtos": produtos, "contatos": contatos,
            "formas_pagamento": formas, "vendedores": vendedores}


async def bling_sync_tick() -> None:
    """Tick do worker. Silencioso e sem excecao quando desligado ou sem OAuth."""
    if not config.enabled():
        return
    try:
        resultado = await sync_all()
        logger.info("[BLING] sync diario: %s", resultado)
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING] sync diario falhou: %s", exc)
