"""Montagem e criacao do pedido de venda no Bling, e projecao em `sales`.

Campos obrigatorios do POST /pedidos/vendas (OpenAPI v3): contato.id, data,
dataSaida, dataPrevista, itens[] e parcelas[]. O contato PRECISA existir antes.

Dinheiro e tratado em Decimal do inicio ao fim. Float acumula erro de
arredondamento e a soma das parcelas precisa fechar EXATAMENTE com o total —
um centavo de diferenca e recusa do Bling.
"""
import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.bling import config
from app.bling.errors import BlingValidationError

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def parse_terms(raw: str | None) -> list[int]:
    """"30/60/90" -> [30, 60, 90]. Vazio ou nao numerico -> [0] (a vista)."""
    if not raw:
        return [0]
    partes = [p.strip() for p in str(raw).replace(",", "/").split("/")]
    dias = [int(p) for p in partes if p.isdigit()]
    return dias or [0]


def item_total(item: dict) -> Decimal:
    bruto = _dec(item["quantidade"]) * _dec(item["valor_unitario"])
    desconto = _dec(item.get("desconto_percentual"))
    return _money(bruto * (Decimal("1") - desconto / Decimal("100")))


def order_total(itens: list[dict]) -> Decimal:
    return _money(sum((item_total(i) for i in itens), Decimal("0")))


def product_summary(itens: list[dict]) -> str:
    """Resumo derivado para `sales.product`, que continua NOT NULL e alimenta a busca."""
    if not itens:
        return "Pedido Bling"
    primeiro = itens[0].get("descricao") or "Item"
    if len(itens) == 1:
        return primeiro
    return f"{primeiro} +{len(itens) - 1} itens"


def build_installments(total: Decimal, terms: list[int], method_id: int | None,
                       sold_at: str) -> list[dict]:
    """Divide o total nas parcelas. A ULTIMA absorve o resto do arredondamento."""
    if not method_id:
        raise BlingValidationError(
            "forma de pagamento e obrigatoria",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )
    if not terms:
        raise BlingValidationError(
            "informe ao menos um prazo de pagamento",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    base = datetime.strptime(sold_at, "%Y-%m-%d").date()
    n = len(terms)
    valor_base = _money(total / Decimal(n))
    parcelas = []
    for i, dias in enumerate(terms):
        if i < n - 1:
            valor = valor_base
        else:
            # Fecha exato: o resto de 100/3 vai para a ultima parcela.
            valor = _money(total - valor_base * Decimal(n - 1))
        parcelas.append({
            "dataVencimento": (base + timedelta(days=int(dias))).isoformat(),
            "valor": float(valor),
            "formaPagamento": {"id": int(method_id)},
        })
    return parcelas


def build_order_payload(*, contact_id: int, sold_at: str, itens: list[dict],
                        payment: dict, seller_id: int | None,
                        discount: dict | None = None, notes: str = "",
                        internal_notes: str = "") -> dict:
    """Monta o corpo do POST /pedidos/vendas."""
    if not itens:
        raise BlingValidationError(
            "o pedido precisa de pelo menos um item",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    total = order_total(itens)
    payload: dict = {
        "contato": {"id": int(contact_id)},
        # O Bling exige as tres datas; sem prazo de entrega definido no CRM,
        # todas recebem a data da venda.
        "data": sold_at,
        "dataSaida": sold_at,
        "dataPrevista": sold_at,
        "itens": [
            {
                "produto": {"id": int(i["bling_product_id"])},
                "codigo": i.get("codigo") or "",
                "unidade": i.get("unidade") or "UN",
                "descricao": i["descricao"],
                "quantidade": float(_dec(i["quantidade"])),
                "valor": float(_dec(i["valor_unitario"])),
                "desconto": float(_dec(i.get("desconto_percentual"))),
            }
            for i in itens
        ],
        "parcelas": build_installments(
            total, payment.get("terms") or [0], payment.get("method_id"), sold_at
        ),
    }

    if seller_id:
        payload["vendedor"] = {"id": int(seller_id)}
    store = config.store_id()
    if store:
        payload["loja"] = {"id": store}
    situacao = config.order_situacao_id()
    if situacao:
        payload["situacao"] = {"id": situacao}
    if discount and _dec(discount.get("valor")) > 0:
        payload["desconto"] = {
            "valor": float(_dec(discount["valor"])),
            "unidade": discount.get("unidade") or "REAL",
        }
    if notes:
        payload["observacoes"] = notes
    if internal_notes:
        payload["observacoesInternas"] = internal_notes
    return payload


# --------------------------------------------------------------------------
# Criacao e projecao em sales
# --------------------------------------------------------------------------
import asyncio  # noqa: E402 — agrupado aqui para manter as funcoes puras acima isoladas

from app.db.supabase import get_supabase  # noqa: E402


def _map_bling_items(pedido: dict) -> list[dict]:
    """Traduz itens do pedido do Bling para linhas de `sale_items`."""
    saida = []
    for ordem, item in enumerate(pedido.get("itens") or []):
        quantidade = _dec(item.get("quantidade"))
        valor = _dec(item.get("valor"))
        desconto = _dec(item.get("desconto"))
        total = _money(quantidade * valor * (Decimal("1") - desconto / Decimal("100")))
        saida.append({
            "bling_product_id": (item.get("produto") or {}).get("id"),
            "codigo": item.get("codigo") or None,
            "descricao": item.get("descricao") or "Item",
            "quantidade": float(quantidade),
            "valor_unitario": float(valor),
            "desconto_percentual": float(desconto),
            "total": float(total),
            "ordem": ordem,
        })
    return saida


def _insert_sale(row: dict) -> str:
    res = get_supabase().table("sales").insert(row).execute()
    return (getattr(res, "data", None) or [{}])[0].get("id")


def _insert_items(sale_id: str, itens: list[dict]) -> None:
    if not itens:
        return
    linhas = [{**i, "sale_id": sale_id} for i in itens]
    get_supabase().table("sale_items").insert(linhas).execute()


async def create_order(client, *, lead_id: str, deal_id: str | None, contact_id: int,
                       sold_at: str, sold_by: str | None, itens: list[dict],
                       payment: dict, seller_id: int | None,
                       discount: dict | None = None, notes: str = "") -> dict:
    """Cria o pedido no Bling e projeta em `sales` + `sale_items`."""
    payload = build_order_payload(
        contact_id=contact_id, sold_at=sold_at, itens=itens, payment=payment,
        seller_id=seller_id, discount=discount, notes=notes,
        internal_notes=f"CRM lead {lead_id}" + (f" - deal {deal_id}" if deal_id else ""),
    )

    criado = await client.post("/pedidos/vendas", payload)
    order_id = int((criado.get("data") or {})["id"])

    # O POST devolve so o id. `numero` e `situacao` resolvidos vem no GET.
    detalhe = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}

    total = order_total(itens)
    linha = {
        "lead_id": lead_id,
        "deal_id": deal_id,
        "sold_at": f"{sold_at}T12:00:00+00:00",
        "value": float(total),
        "product": product_summary(itens),
        "sold_by": sold_by,
        "origin": "crm",
        "status": "registrada",
        "bling_order_id": order_id,
        "bling_order_number": detalhe.get("numero"),
        "bling_situacao_id": (detalhe.get("situacao") or {}).get("id"),
        "payment_method_id": payment.get("method_id"),
        "payment_terms": "/".join(str(d) for d in (payment.get("terms") or [0])),
        "notes": notes or None,
    }
    sale_id = await asyncio.to_thread(_insert_sale, linha)
    await asyncio.to_thread(_insert_items, sale_id, [
        {
            "bling_product_id": i["bling_product_id"],
            "codigo": i.get("codigo"),
            "descricao": i["descricao"],
            "quantidade": float(_dec(i["quantidade"])),
            "valor_unitario": float(_dec(i["valor_unitario"])),
            "desconto_percentual": float(_dec(i.get("desconto_percentual"))),
            "total": float(item_total(i)),
            "ordem": ordem,
        }
        for ordem, i in enumerate(itens)
    ])

    logger.info("[BLING] pedido %s (numero %s) criado para o lead %s",
                order_id, detalhe.get("numero"), lead_id)
    return {
        "sale_id": sale_id,
        "bling_order_id": order_id,
        "bling_order_number": detalhe.get("numero"),
    }


def _existing_sale(order_id: int) -> dict | None:
    res = (get_supabase().table("sales").select("id, origin, deal_id, lead_id")
           .eq("bling_order_id", order_id).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0] if linhas else None


def _upsert_sale(row: dict) -> str | None:
    res = (get_supabase().table("sales")
           .upsert(row, on_conflict="bling_order_id").execute())
    return (getattr(res, "data", None) or [{}])[0].get("id")


def _replace_items(sale_id: str, itens: list[dict]) -> None:
    get_supabase().table("sale_items").delete().eq("sale_id", sale_id).execute()
    if itens:
        get_supabase().table("sale_items").insert(
            [{**i, "sale_id": sale_id} for i in itens]).execute()


async def upsert_from_bling(pedido: dict, *, lead_id: str | None,
                            event_date: str | None) -> str | None:
    """Projeta um pedido do Bling em `sales` (webhook e backfill).

    O UNIQUE em `bling_order_id` faz o pedido que o CRM acabou de criar casar com
    a linha ja gravada — nao duplica quando o webhook volta.
    """
    order_id = int(pedido["id"])
    existente = await asyncio.to_thread(_existing_sale, order_id)

    linha = {
        "bling_order_id": order_id,
        "lead_id": (existente or {}).get("lead_id") or lead_id,
        # Venda vinda do ERP entra sem deal (D7); venda do CRM mantem o dela.
        "deal_id": (existente or {}).get("deal_id"),
        "sold_at": f"{pedido.get('data')}T12:00:00+00:00",
        "value": float(_dec(pedido.get("total"))),
        "product": product_summary(_map_bling_items(pedido)),
        # A origem e imutavel depois de definida: o webhook de volta nao pode
        # reescrever 'crm' para 'bling'.
        "origin": (existente or {}).get("origin") or "bling",
        "status": "registrada",
        "bling_order_number": pedido.get("numero"),
        "bling_situacao_id": (pedido.get("situacao") or {}).get("id"),
        "bling_event_date": event_date,
    }
    sale_id = await asyncio.to_thread(_upsert_sale, linha)
    if sale_id:
        await asyncio.to_thread(_replace_items, sale_id, _map_bling_items(pedido))
    return sale_id


def _update_sale(order_id: int, payload: dict) -> None:
    (get_supabase().table("sales").update(payload)
     .eq("bling_order_id", order_id).execute())


async def cancel_from_bling(order_id: int, *, event_date: str | None) -> None:
    """`order.deleted`: marca cancelada, preserva linha e itens."""
    await asyncio.to_thread(_update_sale, int(order_id), {
        "status": "cancelada", "bling_event_date": event_date,
    })
