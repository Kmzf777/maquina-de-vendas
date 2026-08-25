"""Paridade de números com o frontend — desconto, total e parcelas do orçamento.

═══════════════════════════════════════════════════════════════════════════
CONTRATO DE PARIDADE — orçamento: desconto, total e parcelas
───────────────────────────────────────────────────────────────────────────
ESTA TABELA É COPIADA LITERALMENTE DE `frontend/src/lib/quote-state-parity.test.ts`.
Os mesmos números, os mesmos casos.

Por quê: o vendedor vê o desconto, o total e as parcelas na tela ANTES de
salvar, e o backend recalcula tudo do zero para montar o payload do Bling. Se
as duas contas divergirem em um centavo, ou o Bling recusa a proposta (a soma
das parcelas tem que fechar com o total) ou — pior — aceita um número
diferente do que foi prometido ao cliente, sem erro nenhum para denunciar.
É a mesma disciplina que `bling.ts` já documenta para o pedido de venda.

Regras que os dois lados implementam:
  resolve_discount(subtotal, unidade=..., valor=...)
    PERCENTUAL -> subtotal * valor / 100 ; REAL -> valor
    arredonda em centavo com HALF_UP; satura no subtotal; valor <= 0 -> 0
  quote_total(itens, discount_value=..., freight=...) = subtotal - desconto + frete
    (o frete ENTRA no total e é parcelado junto — é o que o cliente paga)
  build_installments(total, prazos, ...) — a última parcela absorve o resto

O valor digitado — em % ou em R$ — é tratado com no máximo 3 casas decimais
dos dois lados, porque é o que `quotes.discount_input numeric(12,3)` guarda:
uma quarta casa não sobreviveria ao INSERT e não pode mudar o total exibido na
tela. O frontend já manda o número normalizado nessas 3 casas no payload, de
modo que o backend recalcula a partir EXATAMENTE do valor que a tela usou.

 #  | subtotal | desconto        | = desconto R$ | frete  | = total  | prazos               | parcelas
----|----------|-----------------|---------------|--------|----------|----------------------|-----------------------------------
 P1 |   100,00 | 33%             |        33,00  |   0,00 |    67,00 | [0]                  | 67,00
 P2 |    10,01 | 50%             |         5,01  |   0,00 |     5,00 | [0]                  | 5,00
 P3 |    89,90 | 12,5%           |        11,24  |   0,00 |    78,66 | [30,60]              | 39,33 · 39,33
 P4 | 3.525,00 | 23,58%          |       831,20  |   0,00 | 2.693,80 | [30,60,90]           | 897,93 · 897,93 · 897,94
 P5 |    80,10 | 7,5%            |         6,01  |   0,00 |    74,09 | [30,60]              | 37,05 · 37,04
 P6 |   120,00 | 150%            |       120,00  |   0,00 |     0,00 | [0]                  | (recusado: sem centavo a dividir)
 R1 |   267,00 | R$ 26,70        |        26,70  |  35,50 |   275,80 | [30,60]              | 137,90 · 137,90
 R2 |   100,00 | R$ 16,025       |        16,03  |   0,00 |    83,97 | [0]                  | 83,97
 R3 |    50,00 | R$ 80,00        |        50,00  |  12,00 |    12,00 | [0]                  | 12,00
 Z1 |    42,00 | (sem desconto)  |         0,00  |   0,00 |    42,00 | [0]                  | 42,00
 Z2 |    42,00 | R$ -5,00        |         0,00  |   0,00 |    42,00 | [0]                  | 42,00
 F1 |    70,00 | (sem desconto)  |         0,00  |  30,00 |   100,00 | [0,30,60]            | 33,33 · 33,33 · 33,34
 F2 |     8,00 | (sem desconto)  |         0,00  |   2,00 |    10,00 | [0,30,60,90,120,150] | 1,67 ×5 · 1,65
 F3 |   200,00 | 33%             |        66,00  |  15,90 |   149,90 | [30,60,90]           | 49,97 · 49,97 · 49,96

O que cada caso guarda (não são números aleatórios):
  P2, P3, P5  meio centavo exato — 5,005 / 11,2375 / 6,0075. HALF_UP arredonda
              PARA CIMA nos dois lados; truncar daria um centavo a menos.
  P4          REGRESSÃO DE FLOAT. 3525,00 × 23,58% = 831,20 no Decimal, mas
              `Math.round(352500 * 23.58 / 100)` em JS dá 831,19 — o produto
              em float cai em 83119,49999999999. Por isso o TS multiplica o
              percentual em MILÉSIMOS inteiros antes de dividir. Medido: 1 em
              200.000 combinações erra pela via ingênua, 0 em 700.000 pela via
              inteira.
  P6, R3      saturação: o desconto nunca passa do subtotal. Em P6 o total
              zera e NÃO há parcela possível (o backend responde 422); em R3
              sobra o frete, que não é descontável.
  R2          REGRESSÃO DE FLOAT em REAL: `Math.round(16.025 * 100)` dá 1602
              (R$16,02), porque 16,025 × 100 em binário é 1602,4999999999998;
              o Decimal dá 16,03. Vale para 218 dos 40.000 valores de três
              casas entre R$10 e R$50 — não é uma raridade teórica.
  Z1, Z2      ausência e valor negativo viram zero, nunca crédito.
  F1, F2, F3  o frete compõe o total ANTES do parcelamento. F1 é o clássico
              100,00 em 3x (33,33 · 33,33 · 33,34); em F2 a última parcela é
              MENOR que as demais (half-up na base), o que é o comportamento
              correto e não um bug a "consertar"; F3 tem dízima na divisão
              (149,90 / 3 = 49,9666…).
═══════════════════════════════════════════════════════════════════════════
"""
from decimal import Decimal

import pytest

from app.bling.errors import BlingValidationError
from app.bling.orders import build_installments
from app.quotes.proposals import quote_subtotal, quote_total, resolve_discount

QUOTED_AT = "2026-08-25"


def item(subtotal) -> dict:
    """Uma linha de item cujo total é exatamente `subtotal`.

    A tabela do frontend parte de um SUBTOTAL, mas a assinatura do backend
    (`quote_total(itens, ...)`) parte dos itens — o subtotal é derivado ali
    dentro, e é justamente essa derivação que precisa fechar com a da tela.
    Uma linha de quantidade 1 e valor unitário igual ao subtotal atravessa
    `item_total` de verdade em vez de injetar o número já pronto.
    """
    return {"bling_product_id": 1, "descricao": "Item",
            "quantidade": 1, "valor_unitario": subtotal, "desconto_percentual": 0}


# (nome, subtotal, desconto|None, desconto_em_reais, frete, total, prazos, parcelas|None)
# `parcelas=None` = divisão impossível: o backend levanta 422 e o TS devolve [].
CASOS = [
    ("P1", "100.00", {"unidade": "PERCENTUAL", "valor": "33"}, "33.00", "0",
     "67.00", [0], ["67.00"]),
    ("P2", "10.01", {"unidade": "PERCENTUAL", "valor": "50"}, "5.01", "0",
     "5.00", [0], ["5.00"]),
    ("P3", "89.90", {"unidade": "PERCENTUAL", "valor": "12.5"}, "11.24", "0",
     "78.66", [30, 60], ["39.33", "39.33"]),
    ("P4", "3525.00", {"unidade": "PERCENTUAL", "valor": "23.58"}, "831.20", "0",
     "2693.80", [30, 60, 90], ["897.93", "897.93", "897.94"]),
    ("P5", "80.10", {"unidade": "PERCENTUAL", "valor": "7.5"}, "6.01", "0",
     "74.09", [30, 60], ["37.05", "37.04"]),
    ("P6", "120.00", {"unidade": "PERCENTUAL", "valor": "150"}, "120.00", "0",
     "0.00", [0], None),
    ("R1", "267.00", {"unidade": "REAL", "valor": "26.70"}, "26.70", "35.50",
     "275.80", [30, 60], ["137.90", "137.90"]),
    ("R2", "100.00", {"unidade": "REAL", "valor": "16.025"}, "16.03", "0",
     "83.97", [0], ["83.97"]),
    ("R3", "50.00", {"unidade": "REAL", "valor": "80"}, "50.00", "12.00",
     "12.00", [0], ["12.00"]),
    ("Z1", "42.00", None, "0.00", "0", "42.00", [0], ["42.00"]),
    ("Z2", "42.00", {"unidade": "REAL", "valor": "-5"}, "0.00", "0",
     "42.00", [0], ["42.00"]),
    ("F1", "70.00", None, "0.00", "30.00", "100.00", [0, 30, 60],
     ["33.33", "33.33", "33.34"]),
    ("F2", "8.00", None, "0.00", "2.00", "10.00", [0, 30, 60, 90, 120, 150],
     ["1.67", "1.67", "1.67", "1.67", "1.67", "1.65"]),
    ("F3", "200.00", {"unidade": "PERCENTUAL", "valor": "33"}, "66.00", "15.90",
     "149.90", [30, 60, 90], ["49.97", "49.97", "49.96"]),
]

IDS = [c[0] for c in CASOS]


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_paridade_do_desconto(caso):
    _nome, subtotal, desconto, esperado, _frete, _total, _prazos, _parcelas = caso
    obtido = resolve_discount(
        Decimal(subtotal),
        unidade=(desconto or {}).get("unidade") or "REAL",
        valor=(desconto or {}).get("valor") or 0,
    )
    assert obtido == Decimal(esperado)


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_paridade_do_total(caso):
    _nome, subtotal, _desconto, desconto_reais, frete, total, _prazos, _parcelas = caso
    obtido = quote_total([item(subtotal)],
                         discount_value=Decimal(desconto_reais),
                         freight=Decimal(frete))
    assert obtido == Decimal(total)


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_paridade_da_cadeia_inteira(caso):
    """Desconto -> total sem número intermediário vindo da tabela.

    Cada função foi conferida isolada acima; aqui a composição, que é como o
    router usa — para nenhum caso passar por sorte de tabela.
    """
    _nome, subtotal, desconto, _dr, frete, total, _prazos, _parcelas = caso
    itens = [item(subtotal)]
    assert quote_subtotal(itens) == Decimal(subtotal)
    valor = resolve_discount(
        quote_subtotal(itens),
        unidade=(desconto or {}).get("unidade") or "REAL",
        valor=(desconto or {}).get("valor") or 0,
    )
    assert quote_total(itens, discount_value=valor,
                       freight=Decimal(frete)) == Decimal(total)


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_paridade_das_parcelas_sobre_o_total_com_frete(caso):
    """As parcelas dividem o total COM frete e COM desconto.

    `build_installments` é importada de `app.bling.orders` — a mesma função da
    venda, sem uma segunda implementação. Se o orçamento dividisse diferente do
    pedido, converter um orçamento em venda mudaria as parcelas no ERP.
    """
    nome, _subtotal, _desconto, _dr, _frete, total, prazos, esperadas = caso

    if esperadas is None:
        # P6: total zerado. Sem centavo para dividir, o backend recusa com 422
        # ("alguma parcela ficaria sem valor") — o TS devolve [] e o resumo
        # mostra nada, em vez de uma parcela de R$ 0,00.
        with pytest.raises(BlingValidationError):
            build_installments(Decimal(total), prazos, 45, QUOTED_AT)
        return

    parcelas = build_installments(Decimal(total), prazos, 45, QUOTED_AT)
    obtidas = [Decimal(str(p["valor"])) for p in parcelas]
    assert obtidas == [Decimal(v) for v in esperadas], nome
    # A soma tem que fechar EXATAMENTE com o total: um centavo sobrando é
    # recusa do Bling.
    assert sum(obtidas) == Decimal(total)


def test_subtotal_soma_os_itens_ja_com_desconto_de_item():
    """O subtotal é a soma de `item_total`, que já aplica o desconto POR item.

    O desconto de cabeçalho incide sobre esse número — se incidisse sobre o
    bruto, um item com 10% de desconto seria descontado duas vezes.
    """
    itens = [
        {"quantidade": 2, "valor_unitario": "10.00", "desconto_percentual": 10},
        {"quantidade": 1, "valor_unitario": "5.55", "desconto_percentual": 0},
    ]
    assert quote_subtotal(itens) == Decimal("23.55")


def test_total_nao_clampa_em_zero():
    """Espelho literal do `quoteTotal` do TS: quem impede total negativo é a
    saturação do `resolve_discount`, não um clamp aqui.

    Um clamp só deste lado criaria exatamente a divergência que o teste de
    paridade existe para impedir.
    """
    assert quote_total([item("10.00")], discount_value=Decimal("30.00"),
                       freight=Decimal("0")) == Decimal("-20.00")
