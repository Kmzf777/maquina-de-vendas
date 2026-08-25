"""`resolve_discount` — o desconto de cabeçalho do orçamento, em reais.

A tabela completa de paridade com o frontend está em `test_quotes_total.py`
(os 14 casos, copiados de `frontend/src/lib/quote-state-parity.test.ts`). Aqui
ficam as regras isoladas, uma a uma, incluindo as duas armadilhas de float que
motivaram a aritmética em milésimos do lado do TS.

Por que o desconto é convertido para REAIS antes de tudo: a proposta comercial
do Bling recebe `desconto` como número PURO — não existe o par
`{valor, unidade}` que o pedido de venda usa (§10, risco 1 da spec). Guardamos
o par digitado em `quotes.discount_unit` + `discount_input` só para a tela
reexibir "10%" onde o vendedor digitou 10; quem manda no total e no ERP é o
valor em reais.
"""
from decimal import Decimal

import pytest

from app.quotes.proposals import resolve_discount


def desconto(subtotal, unidade, valor) -> Decimal:
    return resolve_discount(Decimal(subtotal), unidade=unidade, valor=valor)


def test_percentual_incide_sobre_o_subtotal():
    assert desconto("100.00", "PERCENTUAL", "33") == Decimal("33.00")


def test_real_e_o_valor_absoluto():
    assert desconto("267.00", "REAL", "26.70") == Decimal("26.70")


def test_unidade_desconhecida_cai_em_real():
    """Qualquer coisa que não seja PERCENTUAL é tratada como reais — a mesma
    regra do `apply_discount` do pedido de venda. Um typo na unidade que virasse
    percentual transformaria R$ 26,70 de desconto em 26,70% do pedido."""
    assert desconto("100.00", "", "10") == Decimal("10.00")
    assert desconto("100.00", "REAIS", "10") == Decimal("10.00")


def test_unidade_e_case_insensitive():
    """A tela manda em caixa alta, mas o valor atravessa banco e proxy; comparar
    literal deixaria 'percentual' virar desconto em reais silenciosamente."""
    assert desconto("100.00", "percentual", "33") == Decimal("33.00")


@pytest.mark.parametrize("valor", ["0", "-5", "-0.001"])
def test_valor_nao_positivo_nunca_vira_credito(valor):
    assert desconto("42.00", "REAL", valor) == Decimal("0.00")
    assert desconto("42.00", "PERCENTUAL", valor) == Decimal("0.00")


def test_sem_subtotal_nao_ha_desconto():
    """Orçamento sem item (ou com total zerado) não tem sobre o que descontar —
    e 10% de zero em percentual daria zero de qualquer jeito, mas em REAIS um
    desconto de R$ 10,00 sem subtotal produziria total negativo."""
    assert desconto("0", "REAL", "10") == Decimal("0.00")
    assert desconto("0", "PERCENTUAL", "10") == Decimal("0.00")


def test_desconto_maior_que_o_subtotal_satura():
    """Satura no subtotal, não estoura para o negativo.

    É o oposto do `apply_discount` do pedido de venda, onde o líquido negativo é
    deixado de propósito para aparecer na mensagem de erro das parcelas. Aqui o
    vendedor vê o resumo antes de salvar, então saturar é o que ele consegue
    entender sem ler um 422 — e o TS faz exatamente isto (casos P6 e R3).
    """
    assert desconto("50.00", "REAL", "80") == Decimal("50.00")
    assert desconto("120.00", "PERCENTUAL", "150") == Decimal("120.00")


def test_meio_centavo_arredonda_para_cima():
    """HALF_UP nos dois lados. 50% de 10,01 = 5,005 -> 5,01, nunca 5,00."""
    assert desconto("10.01", "PERCENTUAL", "50") == Decimal("5.01")
    assert desconto("89.90", "PERCENTUAL", "12.5") == Decimal("11.24")
    assert desconto("80.10", "PERCENTUAL", "7.5") == Decimal("6.01")


def test_armadilha_de_float_no_percentual():
    """P4: 23,58% de 3.525,00 é 831,20, não 831,19.

    `Math.round(352500 * 23.58 / 100)` em JS dá 83119 porque o produto em float
    cai em 8311949,999999999 — por isso o TS passa por milésimos inteiros. Do
    lado Python o Decimal já é exato; o teste existe para provar que o número
    de referência é 831,20 e não o que a via ingênua produziria.
    """
    assert desconto("3525.00", "PERCENTUAL", "23.58") == Decimal("831.20")


def test_armadilha_de_float_no_real():
    """R2: R$ 16,025 de desconto vira 16,03, não 16,02.

    `Math.round(16.025 * 100)` = 1602 (o produto em binário é
    1602,4999999999998). O Decimal quantiza para 16,03 — e é este o número que
    a tela também mostra, porque o TS passa por milésimos.
    """
    assert desconto("100.00", "REAL", "16.025") == Decimal("16.03")


def test_quarta_casa_decimal_e_normalizada_antes_da_conta():
    """`quotes.discount_input` é `numeric(12,3)`: uma quarta casa não sobrevive
    ao INSERT, então também não pode mudar o número que sai daqui. O frontend já
    manda normalizado; o backend normaliza de novo para não depender disso —
    caso contrário o valor gravado e o valor calculado divergiriam.
    """
    assert desconto("100.00", "REAL", "16.0254") == Decimal("16.03")
    assert desconto("100.00", "REAL", "16.0255") == Decimal("16.03")
    # 3 casas: 16,026 -> 16,03 (o arredondamento em centavos vem depois).
    assert desconto("100.00", "REAL", "16.026") == Decimal("16.03")


def test_aceita_numero_em_qualquer_formato_de_entrada():
    """O valor chega do JSON (float), do banco (str) ou já em Decimal. Os três
    caminhos precisam dar o mesmo número — `float` cru é o único que traria
    resíduo binário, e é justamente por isso que a conversão passa por `str`."""
    assert desconto("100.00", "REAL", 16.025) == Decimal("16.03")
    assert desconto("100.00", "REAL", "16.025") == Decimal("16.03")
    assert desconto("100.00", "REAL", Decimal("16.025")) == Decimal("16.03")


def test_resultado_sempre_tem_duas_casas():
    """O valor vai para `quotes.discount_value numeric(12,2)` e para o campo
    `desconto` do Bling. Mais de duas casas seria truncado por um dos dois, em
    silêncio, e o total gravado deixaria de bater com a soma das parcelas."""
    assert desconto("33.33", "PERCENTUAL", "33.333").as_tuple().exponent == -2
