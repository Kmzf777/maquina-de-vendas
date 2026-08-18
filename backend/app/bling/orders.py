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


def apply_discount(total: Decimal, discount: dict | None) -> Decimal:
    """Total LIQUIDO: o desconto de cabecalho reduz o que sera parcelado.

    O Bling aceita 'REAL' (valor absoluto) e 'PERCENTUAL' (% sobre o total dos
    itens). Parcelar o bruto cobraria do cliente mais do que o pedido vale — e
    gravaria receita inflada em `sales.value`. Desconto maior que o total deixa
    o liquido negativo de proposito: a guarda de `build_installments` recusa e o
    valor negativo aparece na mensagem, em vez de virar zero silencioso.
    """
    if not discount:
        return total
    valor = _dec(discount.get("valor"))
    if valor <= 0:
        return total
    if str(discount.get("unidade") or "REAL").upper() == "PERCENTUAL":
        return _money(total * (Decimal("1") - valor / Decimal("100")))
    return _money(total - valor)


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

    n = len(terms)
    valor_base = _money(total / Decimal(n))
    valor_ultima = _money(total - valor_base * Decimal(n - 1))

    # Sem centavos suficientes a divisao produz parcela invalida, de DUAS formas
    # distintas — as duas precisam ser barradas:
    #   valor_base == 0   -> 0,03 em 12x = onze parcelas de ZERO e uma de 0,03;
    #   valor_ultima <= 0 -> 0,06 em 4x  = 0,02+0,02+0,02+0,00 (a base arredonda
    #                        para cima e nao sobra nada), e 0,02 em 4x chega a
    #                        ficar NEGATIVA.
    # O Bling recusaria, mas com um erro que nao menciona parcelas; recusar aqui
    # diz ao vendedor exatamente qual e o problema.
    if valor_base <= 0 or valor_ultima <= 0:
        valor_brl = f"{total:.2f}".replace(".", ",")  # so o numero vira virgula
        raise BlingValidationError(
            f"nao e possivel dividir R$ {valor_brl} em {n} parcelas: "
            "alguma parcela ficaria sem valor",
            type_="VALIDATION_ERROR", status=422,
        )

    base = datetime.strptime(sold_at, "%Y-%m-%d").date()
    parcelas = []
    for i, dias in enumerate(terms):
        # Fecha exato: o resto de 100/3 vai para a ultima parcela.
        valor = valor_base if i < n - 1 else valor_ultima
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

    # Produto do CRM sem mapeamento no Bling faria int(None) estourar TypeError
    # la embaixo — 500 opaco em vez de 422 legivel. A mensagem cita a descricao
    # porque o vendedor precisa saber QUAL produto esta sem vinculo.
    sem_vinculo = [str(i.get("descricao") or "item sem descricao")
                   for i in itens if not i.get("bling_product_id")]
    if sem_vinculo:
        raise BlingValidationError(
            "produto sem vinculo com o Bling: " + ", ".join(sem_vinculo),
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    # As parcelas dividem o LIQUIDO. O desconto de cabecalho e aplicado antes de
    # parcelar, senao a soma das parcelas fica maior que o total do pedido.
    total = apply_discount(order_total(itens), discount)
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

    # ---- daqui para baixo o pedido JA EXISTE no ERP ----
    # Gravar a linha com o bling_order_id vem antes de qualquer coisa que possa
    # falhar. Se uma excecao subisse daqui, o worker de fila retentaria
    # create_order e faria um SEGUNDO POST: pedido duplicado no Bling, estoque
    # baixado duas vezes. O bling_order_id na `sales` e a chave que amarra o
    # pedido ao CRM, entao ele e o primeiro a ser persistido.
    total = apply_discount(order_total(itens), discount)
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
        # `numero` e a situacao resolvida so existem apos o GET abaixo; sao
        # cosmeticos e o webhook order.updated os completa se o GET falhar.
        "bling_order_number": None,
        "bling_situacao_id": None,
        "payment_method_id": payment.get("method_id"),
        "payment_terms": "/".join(str(d) for d in (payment.get("terms") or [0])),
        "notes": notes or None,
    }
    sale_id = await asyncio.to_thread(_insert_sale, linha)

    # Itens e enriquecimento sao best-effort pelo mesmo motivo: uma falha aqui
    # nao pode virar retentativa, porque a retentativa duplica o pedido. Os dois
    # sao recuperaveis — `upsert_from_bling` reescreve itens e numero quando o
    # order.updated chegar.
    try:
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
    except Exception:
        logger.exception("[BLING] pedido %s criado, mas falhou ao gravar os itens",
                         order_id)

    numero = None
    try:
        # O POST devolve so o id. `numero` e a situacao resolvida vem no GET.
        detalhe = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}
        numero = detalhe.get("numero")
        await asyncio.to_thread(_update_sale, order_id, {
            "bling_order_number": numero,
            "bling_situacao_id": (detalhe.get("situacao") or {}).get("id"),
        })
    except Exception:
        logger.warning("[BLING] pedido %s criado, mas o GET de detalhe falhou; "
                       "numero e situacao ficam para o webhook", order_id,
                       exc_info=True)

    logger.info("[BLING] pedido %s (numero %s) criado para o lead %s",
                order_id, numero, lead_id)
    return {
        "sale_id": sale_id,
        "bling_order_id": order_id,
        "bling_order_number": numero,
    }


def _existing_sale(order_id: int) -> dict | None:
    res = (get_supabase().table("sales").select("id, origin, deal_id, lead_id, status")
           .eq("bling_order_id", order_id).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return linhas[0] if linhas else None


def _sold_at_iso(pedido: dict, event_date: str | None) -> str | None:
    """Data da venda em timestamptz. Sem guarda, um pedido sem `data` viraria a
    string "NoneT12:00:00+00:00" e explodiria no Postgres no meio do webhook."""
    data = str(pedido.get("data") or "").strip()
    if data:
        return f"{data}T12:00:00+00:00"
    return event_date or None


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

    # Payload de webhook costuma vir RESUMIDO, sem `itens`. Nesse caso nao
    # tocamos em sale_items nem em `product`: um order.updated magro apagaria os
    # itens que o CRM acabou de gravar completos e reescreveria o resumo do
    # produto para "Pedido Bling".
    traz_itens = bool(pedido.get("itens"))

    linha = {
        "bling_order_id": order_id,
        "lead_id": (existente or {}).get("lead_id") or lead_id,
        # Venda vinda do ERP entra sem deal (D7); venda do CRM mantem o dela.
        "deal_id": (existente or {}).get("deal_id"),
        "value": float(_dec(pedido.get("total"))),
        # A origem e imutavel depois de definida: o webhook de volta nao pode
        # reescrever 'crm' para 'bling'.
        "origin": (existente or {}).get("origin") or "bling",
        # Venda ja cancelada nao volta a 'registrada' no proximo evento.
        "status": ("cancelada" if (existente or {}).get("status") == "cancelada"
                   else "registrada"),
        "bling_order_number": pedido.get("numero"),
        "bling_situacao_id": (pedido.get("situacao") or {}).get("id"),
        "bling_event_date": event_date,
    }

    sold_at = _sold_at_iso(pedido, event_date)
    if sold_at:
        linha["sold_at"] = sold_at

    if traz_itens:
        linha["product"] = product_summary(_map_bling_items(pedido))
    elif not existente:
        # Venda nova sem itens no payload: `product` e NOT NULL e precisa de algo.
        linha["product"] = "Pedido Bling"

    sale_id = await asyncio.to_thread(_upsert_sale, linha)
    if sale_id and traz_itens:
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
