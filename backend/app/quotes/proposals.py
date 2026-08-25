"""Montagem e criação da PROPOSTA COMERCIAL no Bling (o orçamento do CRM).

Este módulo é o gêmeo de `app/bling/orders.py`, e a semelhança é proposital:
tudo que os dois compartilham — total do item, divisão das parcelas, leitura de
prazos — é IMPORTADO de lá, nunca reescrito. A razão é dura: um orçamento vira
pedido de venda com um clique, e se as duas contas divergirem em um centavo a
conversão muda o valor que foi prometido ao cliente. A divisão de parcela em
especial tem que ser byte a byte a mesma, porque a soma das parcelas precisa
fechar EXATAMENTE com o total nos dois recursos do Bling.

O que a proposta comercial NÃO compartilha com o pedido de venda — e cada
diferença abaixo é uma falha silenciosa esperando acontecer se for ignorada:

* **`desconto` é um número puro**, sem o par `{valor, unidade}` do pedido
  (`VendasDescontoDTO`). A leitura mais provável é que seja em REAIS, porque o
  campo irmão `outrasDespesas` claramente é — mas isso é uma inferência da spec
  OpenAPI, não uma confirmação (§10, risco 1). Convertemos `%` para reais aqui;
  se a leitura estiver errada, o desconto sai multiplicado por cem no ERP.
* **A descrição do item mora em `itens[].produto.descricao`**, e não em
  `itens[].descricao` como no pedido. Copiar do pedido faz o item chegar sem
  descrição.
* **A observação interna é `observacaoInterna`** (singular). No pedido é
  `observacoesInternas`. A chave errada é descartada sem erro.
* **O frete viaja em `transporte.frete` + `transporte.freteModalidade`**, nunca
  em `outrasDespesas`: a modalidade (CIF/FOB/terceiros) é o que o ERP precisa
  para emitir a nota, e despesa genérica perde essa informação.
* **`id`, `total` e `totalProdutos` são `readOnly`.** O Bling calcula o total a
  partir dos itens; mandar o nosso ou é ignorado (dando falsa impressão de que
  foi aceito) ou entra em conflito com a soma das parcelas.

Todo dinheiro em `Decimal` com `ROUND_HALF_UP`, do início ao fim. Float acumula
resíduo binário e o resíduo aparece justamente no meio do centavo — ver os
casos P4 e R2 da tabela de paridade em `tests/test_quotes_total.py`.

Referência: `docs/reference/bling-propostas-comerciais.openapi.json`.
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

from app.bling.errors import BlingValidationError
from app.bling.orders import _dec, _money, build_installments, order_total

logger = logging.getLogger(__name__)

# O que o vendedor digita é guardado em `quotes.discount_input numeric(12,3)`.
# Uma quarta casa não sobrevive ao INSERT, então também não pode influenciar o
# total — normalizar aqui é o que garante que o número calculado e o número
# gravado sejam o mesmo. O frontend já manda normalizado (`milesimos()` no
# `quote-state.ts`); repetir a normalização é o que torna a paridade
# independente de o frontend continuar fazendo isso.
_MILESIMO = Decimal("0.001")

# Enum literal da spec — COM acento e COM a caixa exata. 'Nao aprovado' sem til
# é recusado pelo Bling.
SITUACOES = ("Pendente", "Aguardando", "Não aprovado", "Aprovado", "Concluído",
             "Rascunho")

# Decisão 2 da spec: o orçamento nasce Rascunho. É o que impede uma proposta em
# negociação de aparecer como pendente de faturamento no ERP.
SITUACAO_INICIAL = "Rascunho"

# `quotes.status` é vocabulário NOSSO (caixa baixa, sem acento); a situação do
# Bling é outra coisa e vive em `quotes.bling_situacao`. Os dois são campos
# distintos de propósito: o PATCH de situação pode falhar sem invalidar o
# estado local.
STATUS_SITUACAO = {
    "rascunho": "Rascunho",
    "enviado": "Pendente",
    "aprovado": "Aprovado",
    "nao_aprovado": "Não aprovado",
    # Convertido é "Aprovado" no ERP: a proposta virou pedido de venda.
    "convertido": "Aprovado",
    # Cancelado também vira "Não aprovado" — não existe situação de cancelamento
    # na proposta comercial, e o DELETE está fora de escopo (§11).
    "cancelado": "Não aprovado",
}

# Enum de `transporte.freteModalidade`.
MODALIDADES_FRETE = (0, 1, 2, 3, 4, 9)


# --------------------------------------------------------------------------
# Dinheiro
# --------------------------------------------------------------------------
def normalize_discount_input(valor) -> Decimal:
    """O número que o vendedor digitou, normalizado nas 3 casas da coluna.

    É o valor que vai para `quotes.discount_input` e o mesmo de que
    `resolve_discount` parte — se os dois divergissem, o desconto exibido na
    reabertura do orçamento não reproduziria o total gravado. Negativo vira
    zero: o campo existe para a tela reexibir o que foi digitado, e reexibir
    "-5" ao lado de um desconto de R$ 0,00 confunde mais do que informa.
    """
    bruto = _dec(valor).quantize(_MILESIMO, rounding=ROUND_HALF_UP)
    return bruto if bruto > 0 else Decimal("0.000")


def resolve_discount(subtotal: Decimal, *, unidade: str, valor) -> Decimal:
    """Desconto de cabeçalho convertido para REAIS.

    `PERCENTUAL` incide sobre o subtotal (que já vem com os descontos de item
    aplicados); qualquer outra unidade é tratada como valor absoluto — a mesma
    regra permissiva do `apply_discount` do pedido, porque um typo na unidade
    virando percentual transformaria R$ 26,70 de desconto em 26,70% do pedido.

    SATURA no subtotal. Isto é o oposto do que `apply_discount` faz na venda,
    onde o líquido negativo é deixado de propósito para aparecer na mensagem de
    erro das parcelas. Aqui o vendedor vê o resumo na tela ANTES de salvar, e o
    frontend satura (`resolveDiscount` em `quote-state.ts`) — divergir seria
    exibir um número e gravar outro.

    Valor nulo, zero ou negativo devolve 0: nunca crédito.
    """
    subtotal = _money(_dec(subtotal))
    if subtotal <= 0:
        return Decimal("0.00")

    # Normaliza em 3 casas ANTES de qualquer conta (ver `_MILESIMO`).
    bruto = normalize_discount_input(valor)
    if bruto <= 0:
        return Decimal("0.00")

    if str(unidade or "REAL").upper() == "PERCENTUAL":
        desconto = _money(subtotal * bruto / Decimal("100"))
    else:
        desconto = _money(bruto)

    return min(desconto, subtotal)


def quote_subtotal(itens: list[dict]) -> Decimal:
    """Soma dos itens, cada um já com o SEU desconto percentual aplicado.

    É `order_total` de `app/bling/orders.py` sob outro nome — o alias existe
    para o vocabulário do módulo ficar em português do orçamento sem duplicar a
    conta. O desconto de cabeçalho incide sobre este número; se incidisse sobre
    o bruto, um item com 10% de desconto seria descontado duas vezes.
    """
    return order_total(itens)


def quote_total(itens: list[dict], *, discount_value: Decimal,
                freight: Decimal) -> Decimal:
    """`subtotal - desconto + frete`.

    O frete ENTRA no total e é parcelado junto (§4 da spec): é dinheiro que o
    cliente vai pagar, e deixá-lo fora faria a soma das parcelas não fechar com
    o total da proposta — recusa do Bling.

    Não clampa em zero de propósito: é espelho literal do `quoteTotal` do TS, e
    quem impede o total negativo é a saturação do `resolve_discount`. Um clamp
    só deste lado criaria exatamente a divergência que o teste de paridade
    existe para impedir.
    """
    return (_money(quote_subtotal(itens))
            - _money(_dec(discount_value))
            + _money(_dec(freight)))


def normalize_freight(freight) -> Decimal:
    """Frete em centavos, nunca negativo.

    Frete negativo seria desconto disfarçado — e furaria a garantia de que o
    total não fica abaixo de zero, já que a saturação do desconto só olha o
    subtotal. Mesma regra do `buildQuotePayload` no `quote-state.ts`.
    """
    valor = _money(_dec(freight))
    return valor if valor > 0 else Decimal("0.00")


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------
def build_proposal_payload(*, contact_id: int, quoted_at: str, itens: list[dict],
                           discount_value: Decimal, freight: Decimal,
                           freight_mode: int | None, method_id: int | None,
                           terms: list[int], seller_id: int | None,
                           store_id: int | None, situacao: str = SITUACAO_INICIAL,
                           notes: str = "", internal_notes: str = "",
                           aos_cuidados_de: str = "") -> dict:
    """Corpo do POST/PUT /propostas-comerciais.

    Só `itens[]` e `parcelas[]` são obrigatórios pela spec; o resto viaja
    condicionalmente. Campo ausente e campo com zero não são a mesma coisa para
    um ERP que registra histórico de alteração da proposta — por isso desconto,
    frete, loja, vendedor e observações só entram quando têm conteúdo.
    """
    if not itens:
        raise BlingValidationError(
            "o orcamento precisa de pelo menos um item",
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    # Produto do CRM sem mapeamento no Bling faria int(None) estourar TypeError
    # aqui embaixo — 500 opaco em vez de 422 legível. A mensagem cita a
    # descrição porque o vendedor precisa saber QUAL produto está sem vínculo.
    sem_vinculo = [str(i.get("descricao") or "item sem descricao")
                   for i in itens if not i.get("bling_product_id")]
    if sem_vinculo:
        raise BlingValidationError(
            "produto sem vinculo com o Bling: " + ", ".join(sem_vinculo),
            type_="MISSING_REQUIRED_FIELD_ERROR", status=422,
        )

    if situacao not in SITUACOES:
        raise BlingValidationError(
            f"situacao invalida para proposta comercial: {situacao!r}",
            type_="VALIDATION_ERROR", status=422,
        )

    frete = normalize_freight(freight)
    if freight_mode is not None and int(freight_mode) not in MODALIDADES_FRETE:
        raise BlingValidationError(
            f"modalidade de frete invalida: {freight_mode} "
            "(0 CIF, 1 FOB, 2 terceiros, 3/4 proprio, 9 sem transporte)",
            type_="VALIDATION_ERROR", status=422,
        )

    desconto = _money(_dec(discount_value))
    total = quote_total(itens, discount_value=desconto, freight=frete)

    payload: dict = {
        "data": quoted_at,
        "situacao": situacao,
        "contato": {"id": int(contact_id)},
        "itens": [
            {
                # A descrição vai DENTRO de `produto` — diferença real para o
                # pedido de venda, onde ela é campo do item.
                "produto": {
                    "id": int(i["bling_product_id"]),
                    "descricao": i.get("descricao") or "Item",
                },
                "codigo": i.get("codigo") or "",
                "unidade": i.get("unidade") or "UN",
                "quantidade": float(_dec(i["quantidade"])),
                "valor": float(_dec(i["valor_unitario"])),
                # No item o desconto é PERCENTUAL; no cabeçalho, reais. Trocar
                # os dois transforma 10% em R$ 10,00 sem erro nenhum.
                "desconto": float(_dec(i.get("desconto_percentual"))),
            }
            for i in itens
        ],
        # As parcelas dividem o total COM frete e COM desconto — é o que o
        # cliente paga. Função importada da venda: divisão idêntica, sempre.
        "parcelas": build_installments(total, terms or [0], method_id, quoted_at),
    }

    if desconto > 0:
        # Número puro, em reais (ver o docstring do módulo sobre o risco 1).
        payload["desconto"] = float(desconto)

    transporte: dict = {}
    if frete > 0:
        transporte["frete"] = float(frete)
    if freight_mode is not None:
        transporte["freteModalidade"] = int(freight_mode)
    if transporte:
        payload["transporte"] = transporte

    if seller_id:
        payload["vendedor"] = {"id": int(seller_id)}
    if store_id:
        # `BLING_STORE_ID` não existe no `.env` hoje (§10, risco 4) e `loja` é
        # opcional no POST — `{"id": None}` seria pior do que campo ausente.
        payload["loja"] = {"id": int(store_id)}
    if notes:
        payload["observacoes"] = notes
    if internal_notes:
        payload["observacaoInterna"] = internal_notes
    if aos_cuidados_de:
        payload["aosCuidadosDe"] = aos_cuidados_de

    return payload


# --------------------------------------------------------------------------
# Chamadas ao Bling
# --------------------------------------------------------------------------
async def create_proposal(client, **kwargs) -> dict:
    """Cria a proposta e devolve `{bling_proposal_id, bling_proposal_number}`.

    O POST responde `201 {"data":{"id":N}}` — SÓ o id. O `numero`, que é o que
    sai impresso no PDF e o que o cliente cita ao responder, exige um GET
    seguinte.

    **Esse GET é best-effort, e a regra é contraintuitiva: falhar nele não pode
    derrubar a criação.** No instante em que o POST volta 201 a proposta JÁ
    EXISTE no ERP. Se a exceção subisse, o vendedor veria erro, tentaria de
    novo, e o segundo POST criaria uma SEGUNDA proposta — e, ao contrário do
    pedido de venda (que tem `numeroLoja` como chave de idempotência), a
    proposta comercial não tem campo nenhum onde ancorar uma retentativa
    segura. Duplicata aqui é definitiva. Sem número, o PDF cai no id.
    """
    payload = build_proposal_payload(situacao=SITUACAO_INICIAL, **kwargs)
    criado = await client.post("/propostas-comerciais", payload)

    # 201 sem `data.id` é contrato quebrado: sem id não há como editar, mudar
    # situação ou converter a proposta depois. Falhar alto é melhor do que
    # gravar um orçamento órfão que ninguém consegue mais tocar.
    proposal_id = int((criado.get("data") or {})["id"])

    numero = None
    try:
        detalhe = (await client.get(
            f"/propostas-comerciais/{proposal_id}")).get("data") or {}
        numero = detalhe.get("numero")
    except Exception:
        logger.warning("[QUOTES] proposta %s criada, mas o GET de detalhe "
                       "falhou; o numero fica nulo e o PDF cai no id",
                       proposal_id, exc_info=True)

    logger.info("[QUOTES] proposta %s (numero %s) criada", proposal_id, numero)
    return {"bling_proposal_id": proposal_id, "bling_proposal_number": numero}


async def update_proposal(client, *, proposal_id: int, **kwargs) -> dict:
    """Altera a proposta. Reaproveita o mesmo payload do POST — o Bling não tem
    formato separado para alteração.

    Não trata a recusa: quem chama decide o que fazer com ela, exatamente como
    em `update_order`. E o PUT SUBSTITUI a lista de itens pela que for enviada,
    o que é o motivo de a tela de edição carregar os itens gravados em vez de
    nascer com uma linha em branco.
    """
    payload = build_proposal_payload(**kwargs)
    return await client.put(f"/propostas-comerciais/{proposal_id}", payload)


async def set_situacao(client, *, proposal_id: int, situacao: str) -> None:
    """PATCH /propostas-comerciais/{id}/situacoes.

    PATCH no sub-recurso, e não PUT na proposta: o PUT substituiria a proposta
    inteira pelo corpo enviado, então mandar só `{"situacao": ...}` apagaria
    itens e parcelas.

    Vai por `client.request` porque o `BlingClient` expõe atalhos só para
    GET/POST/PUT — `request` é público e aplica o mesmo rate limit e a mesma
    política de retry dos demais verbos.

    A situação é validada ANTES da chamada: gastar uma requisição do orçamento
    de 3 req/s para descobrir um typo nosso é desperdício, e rajada de erro
    conta para o bloqueio de IP do Bling (300 erros em 10s = 10 min bloqueado).
    """
    if situacao not in SITUACOES:
        raise BlingValidationError(
            f"situacao invalida para proposta comercial: {situacao!r}",
            type_="VALIDATION_ERROR", status=422,
        )
    await client.request("PATCH", f"/propostas-comerciais/{proposal_id}/situacoes",
                         json={"situacao": situacao})


__all__ = [
    "MODALIDADES_FRETE", "SITUACOES", "SITUACAO_INICIAL", "STATUS_SITUACAO",
    "build_proposal_payload", "create_proposal", "normalize_discount_input",
    "normalize_freight", "quote_subtotal", "quote_total", "resolve_discount",
    "set_situacao", "update_proposal",
]
