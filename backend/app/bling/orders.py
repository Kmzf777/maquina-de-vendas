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
