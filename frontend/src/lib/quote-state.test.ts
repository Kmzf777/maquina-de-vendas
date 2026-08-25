import { describe, expect, it } from "vitest";
import { addLine, applyProduct, blankLine, updateLine } from "@/lib/bling-order-state";
import {
  buildQuotePayload,
  linesFromQuoteItems,
  quoteSubtotal,
  quoteTotal,
  resolveDiscount,
  type QuoteMeta,
} from "@/lib/quote-state";
import type { QuoteItem } from "@/lib/types";

const PRODUTOS = [
  { id: 123, codigo: "CAN-CLA-250", nome: "Cafe Canastra Classico Moido 250g",
    preco: 26.7, unidade: "UN", saldo_virtual: 480 },
  { id: 124, codigo: "CAN-SUA-500", nome: "Cafe Canastra Suave Moido 500g",
    preco: 44.9, unidade: "CX", saldo_virtual: 120 },
];

/** Uma linha completa, do jeito que o formulário produz: escolhe o produto no
 *  catálogo (que preenche preço, código e unidade) e ajusta a quantidade. */
const linha = (produtoId: number, patch = {}) =>
  updateLine(applyProduct([blankLine()], 0, produtoId, PRODUTOS), 0, patch)[0];

const META: QuoteMeta = {
  leadId: "L1",
  dealId: "D1",
  conversationId: "C1",
  quotedAt: "2026-08-25",
  createdBy: "vendedor@cafecanastra.com",
  discount: null,
  freight: 0,
  freightMode: null,
  paymentMethodId: 45,
  terms: [30, 60],
  notes: "",
  internalNotes: "",
};

describe("resolveDiscount", () => {
  it("PERCENTUAL aplica a porcentagem sobre o subtotal", () => {
    expect(resolveDiscount(100, { valor: 33, unidade: "PERCENTUAL" })).toBe(33);
    expect(resolveDiscount(267, { valor: 10, unidade: "PERCENTUAL" })).toBe(26.7);
  });

  it("REAL usa o valor digitado como esta", () => {
    expect(resolveDiscount(267, { valor: 26.7, unidade: "REAL" })).toBe(26.7);
  });

  it("arredonda o centavo para cima no meio, como o Decimal do backend", () => {
    // 10,01 x 50% = 5,005 -> 5,01. ROUND_HALF_UP dos dois lados.
    expect(resolveDiscount(10.01, { valor: 50, unidade: "PERCENTUAL" })).toBe(5.01);
    // 89,90 x 12,5% = 11,2375 -> 11,24.
    expect(resolveDiscount(89.9, { valor: 12.5, unidade: "PERCENTUAL" })).toBe(11.24);
  });

  it("nunca passa do subtotal — em REAL e em PERCENTUAL", () => {
    // Saturar em vez de deixar o total negativo: um desconto maior que o pedido
    // é erro de digitação, e um total negativo viraria parcela negativa no ERP.
    expect(resolveDiscount(50, { valor: 80, unidade: "REAL" })).toBe(50);
    expect(resolveDiscount(120, { valor: 150, unidade: "PERCENTUAL" })).toBe(120);
    expect(resolveDiscount(120, { valor: 100, unidade: "PERCENTUAL" })).toBe(120);
  });

  it("sem desconto vale zero: null, zero e negativo", () => {
    expect(resolveDiscount(100, null)).toBe(0);
    expect(resolveDiscount(100, { valor: 0, unidade: "REAL" })).toBe(0);
    expect(resolveDiscount(100, { valor: 0, unidade: "PERCENTUAL" })).toBe(0);
    expect(resolveDiscount(100, { valor: -5, unidade: "REAL" })).toBe(0);
    expect(resolveDiscount(100, { valor: -5, unidade: "PERCENTUAL" })).toBe(0);
  });

  it("subtotal zero ou negativo nao gera desconto", () => {
    // Orçamento ainda sem item: o campo de desconto pode já estar preenchido, e
    // 10% de nada é nada — não um crédito.
    expect(resolveDiscount(0, { valor: 10, unidade: "PERCENTUAL" })).toBe(0);
    expect(resolveDiscount(0, { valor: 10, unidade: "REAL" })).toBe(0);
    expect(resolveDiscount(-5, { valor: 10, unidade: "REAL" })).toBe(0);
  });

  it("respeita as 3 casas do percentual que a coluna guarda", () => {
    // `quotes.discount_input` é numeric(12,3): mais casas que isso não sobrevivem
    // ao INSERT, então também não podem mudar o total exibido na tela.
    expect(resolveDiscount(1000, { valor: 33.333, unidade: "PERCENTUAL" })).toBe(333.33);
  });
});

describe("quoteSubtotal", () => {
  it("soma as linhas ja com o desconto de item", () => {
    const linhas = [
      linha(123, { quantidade: 10 }),                            // 267,00
      linha(124, { quantidade: 2, descontoPercentual: 10 }),     // 80,82
    ];
    expect(quoteSubtotal(linhas)).toBe(347.82);
  });

  it("ignora as linhas que nao entram no payload", () => {
    // O resumo lateral não pode somar dinheiro que o POST não vai enviar: uma
    // linha sem produto (ou com quantidade zero) é descartada em
    // `buildQuotePayload`, então também não conta aqui.
    const linhas = [
      linha(123, { quantidade: 10 }),
      { ...blankLine(), valorUnitario: 999 },     // valor digitado, sem produto
      linha(124, { quantidade: 0 }),              // produto escolhido, sem quantidade
    ];
    expect(quoteSubtotal(linhas)).toBe(267);
  });

  it("formulario vazio vale zero", () => {
    expect(quoteSubtotal([blankLine()])).toBe(0);
    expect(quoteSubtotal([])).toBe(0);
  });
});

describe("quoteTotal", () => {
  it("subtrai o desconto e SOMA o frete", () => {
    expect(quoteTotal(267, 26.7, 35.5)).toBe(275.8);
    expect(quoteTotal(100, 0, 0)).toBe(100);
  });

  it("nao acumula erro de ponto flutuante", () => {
    // 0,1 + 0,2 em float dá 0,30000000000000004; em centavos dá 0,30.
    expect(quoteTotal(0.1, 0, 0.2)).toBe(0.3);
    expect(quoteTotal(1234.56, 111.11, 22.22)).toBe(1145.67);
  });

  it("nao clampa nada — quem satura e o resolveDiscount", () => {
    // Espelho fiel do `quote_total` do backend. Um clamp aqui só de um lado
    // criaria justamente a divergência que o teste de paridade existe para
    // impedir; o desconto grande demais já foi saturado antes de chegar aqui.
    expect(quoteTotal(50, 80, 0)).toBe(-30);
  });
});

describe("buildQuotePayload", () => {
  it("monta o corpo do QuoteIn com subtotal, desconto, frete, total e parcelas", () => {
    const linhas = [linha(123, { quantidade: 10 })];
    const out = buildQuotePayload(linhas, {
      ...META,
      discount: { valor: 10, unidade: "PERCENTUAL" },
      freight: 35.5,
      freightMode: 0,
      notes: "Entrega na filial",
      internalNotes: "Cliente pediu prazo",
    });

    expect(out.valid).toBe(true);
    expect(out.subtotal).toBe(267);
    expect(out.discount).toBe(26.7);
    expect(out.freight).toBe(35.5);
    expect(out.total).toBe(275.8);
    expect(out.payload).toEqual({
      lead_id: "L1",
      deal_id: "D1",
      conversation_id: "C1",
      quoted_at: "2026-08-25",
      created_by: "vendedor@cafecanastra.com",
      items: [{
        bling_product_id: 123,
        codigo: "CAN-CLA-250",
        descricao: "Cafe Canastra Classico Moido 250g",
        unidade: "UN",
        quantidade: 10,
        valor_unitario: 26.7,
        desconto_percentual: 0,
      }],
      discount: { valor: 10, unidade: "PERCENTUAL" },
      freight: 35.5,
      freight_mode: 0,
      payment: { method_id: 45, terms: [30, 60] },
      notes: "Entrega na filial",
      internal_notes: "Cliente pediu prazo",
    });
  });

  it("parcela o total COM o frete, nao so os produtos", () => {
    // O frete é parte do que o cliente vai pagar; parcelar só os produtos
    // deixaria a soma das parcelas menor que o total do orçamento.
    const out = buildQuotePayload([linha(123, { quantidade: 10 })], {
      ...META, discount: { valor: 26.7, unidade: "REAL" }, freight: 35.5,
      terms: [30, 60],
    });
    expect(out.subtotal).toBe(267);
    expect(out.total).toBe(275.8); // 267,00 - 26,70 + 35,50 — o frete sobe o total
    expect(out.installments.map((p) => p.valor)).toEqual([137.9, 137.9]);
    expect(out.installments.map((p) => p.dataVencimento))
      .toEqual(["2026-09-24", "2026-10-24"]);
  });

  it("as parcelas fecham exatamente com o total", () => {
    const out = buildQuotePayload([linha(124, { quantidade: 3 })],
      { ...META, freight: 12.34, discount: { valor: 7, unidade: "PERCENTUAL" },
        terms: [0, 30, 60] });
    const soma = out.installments.reduce((acc, p) => acc + p.valor, 0);
    expect(Math.round(soma * 100) / 100).toBe(out.total);
  });

  it("manda o desconto como o par digitado, nao ja convertido em reais", () => {
    // `quotes` guarda unidade + entrada para reexibir "10%" na edição; se o
    // frontend enviasse só os reais, reabrir o orçamento mostraria "26,70" no
    // campo onde o vendedor digitou "10".
    const out = buildQuotePayload([linha(123, { quantidade: 10 })],
      { ...META, discount: { valor: 10, unidade: "PERCENTUAL" } });
    expect(out.payload.discount).toEqual({ valor: 10, unidade: "PERCENTUAL" });
    expect(out.discount).toBe(26.7);
  });

  it("normaliza o percentual enviado nas 3 casas que a coluna guarda", () => {
    // A tela calculou com 12,346; se o payload levasse 12,3456 o backend
    // recalcularia com um número que a tela nunca usou — e `discount_input`
    // (numeric(12,3)) arredondaria de qualquer forma no INSERT.
    const out = buildQuotePayload([linha(123)], {
      ...META, discount: { valor: 12.3456, unidade: "PERCENTUAL" },
    });
    expect(out.payload.discount).toEqual({ valor: 12.346, unidade: "PERCENTUAL" });
  });

  it("sem desconto o campo vai null, nao um zero disfarcado", () => {
    expect(buildQuotePayload([linha(123)], META).payload.discount).toBeNull();
    expect(buildQuotePayload([linha(123)], {
      ...META, discount: { valor: 0, unidade: "PERCENTUAL" },
    }).payload.discount).toBeNull();
    expect(buildQuotePayload([linha(123)], {
      ...META, discount: { valor: -3, unidade: "REAL" },
    }).payload.discount).toBeNull();
  });

  it("normaliza o frete em centavos e recusa frete negativo", () => {
    // Frete negativo seria desconto disfarçado — e furaria a garantia de que o
    // total nunca fica abaixo de zero.
    expect(buildQuotePayload([linha(123)], { ...META, freight: 10.005 }).freight)
      .toBe(10.01);
    const neg = buildQuotePayload([linha(123)], { ...META, freight: -50 });
    expect(neg.freight).toBe(0);
    expect(neg.payload.freight).toBe(0);
  });

  it("preserva a unidade do item — a proposta no Bling exige o campo", () => {
    const out = buildQuotePayload([linha(124, { quantidade: 2 })], META);
    expect(out.payload.items[0].unidade).toBe("CX");
  });

  it("descarta as linhas incompletas", () => {
    const linhas = addLine([linha(123, { quantidade: 10 })]); // 2a linha em branco
    const out = buildQuotePayload(linhas, META);
    expect(out.valid).toBe(true);
    expect(out.payload.items).toHaveLength(1);
  });

  it("invalido sem nenhuma linha completa", () => {
    expect(buildQuotePayload([blankLine()], META).valid).toBe(false);
    expect(buildQuotePayload([linha(123, { quantidade: 0 })], META).valid).toBe(false);
    expect(buildQuotePayload([], META).valid).toBe(false);
  });

  it("invalido sem forma de pagamento", () => {
    // As parcelas da proposta comercial são obrigatórias no POST do Bling, e
    // toda parcela carrega a forma — sem ela não há o que enviar.
    const out = buildQuotePayload([linha(123)], { ...META, paymentMethodId: null });
    expect(out.valid).toBe(false);
  });

  it("sem prazo nenhum vira a vista, com vencimento na data do orcamento", () => {
    const out = buildQuotePayload([linha(123, { quantidade: 10 })],
      { ...META, terms: [] });
    expect(out.payload.payment.terms).toEqual([0]);
    expect(out.installments).toEqual([
      { dataVencimento: "2026-08-25", valor: 267 },
    ]);
  });

  it("desconto igual ao subtotal deixa so o frete a pagar", () => {
    const out = buildQuotePayload([linha(123, { quantidade: 10 })], {
      ...META, discount: { valor: 500, unidade: "REAL" }, freight: 12,
      terms: [0],
    });
    expect(out.discount).toBe(267);
    expect(out.total).toBe(12);
    expect(out.installments.map((p) => p.valor)).toEqual([12]);
  });

  it("total zerado nao inventa parcela", () => {
    // `buildInstallments` devolve [] quando não há centavo para dividir — o
    // backend recusaria com 422, e o resumo prefere mostrar nada a mostrar
    // uma parcela de R$ 0,00.
    const out = buildQuotePayload([linha(123, { quantidade: 10 })], {
      ...META, discount: { valor: 100, unidade: "PERCENTUAL" }, terms: [0],
    });
    expect(out.total).toBe(0);
    expect(out.installments).toEqual([]);
  });

  it("total nunca fica negativo, por maior que seja o desconto", () => {
    for (const valor of [1000, 99999]) {
      for (const unidade of ["REAL", "PERCENTUAL"] as const) {
        const out = buildQuotePayload([linha(123, { quantidade: 10 })],
          { ...META, discount: { valor, unidade }, freight: 20 });
        expect(out.total).toBeGreaterThanOrEqual(0);
      }
    }
  });
});

describe("linesFromQuoteItems", () => {
  const item = (patch: Partial<QuoteItem>): QuoteItem => ({
    id: "i1", quote_id: "q1", bling_product_id: 123, codigo: "CAN-CLA-250",
    descricao: "Cafe Canastra Classico Moido 250g", unidade: "UN", quantidade: 2,
    valor_unitario: 26.7, desconto_percentual: 0, total: 53.4, ordem: 0,
    ...patch,
  });

  it("converte item em linha preservando produto, codigo, unidade, quantidade, valor e desconto", () => {
    expect(linesFromQuoteItems([item({ desconto_percentual: 10 })])).toEqual([{
      blingProductId: 123,
      descricao: "Cafe Canastra Classico Moido 250g",
      codigo: "CAN-CLA-250",
      unidade: "UN",
      quantidade: 2,
      valorUnitario: 26.7,
      descontoPercentual: 10,
    }]);
  });

  it("respeita a ordem gravada, mesmo com os itens fora de ordem", () => {
    const linhas = linesFromQuoteItems([
      item({ id: "b", descricao: "Segundo", ordem: 1 }),
      item({ id: "a", descricao: "Primeiro", ordem: 0 }),
    ]);
    expect(linhas.map((l) => l.descricao)).toEqual(["Primeiro", "Segundo"]);
  });

  it("converte numeros que o PostgREST devolve como string", () => {
    // `numeric` volta como string no JSON do PostgREST dependendo da rota; sem
    // o Number() a quantidade viraria "2" e a aritmética somaria texto.
    const bruto = item({
      quantidade: "3" as unknown as number,
      valor_unitario: "26.70" as unknown as number,
      desconto_percentual: "5" as unknown as number,
    });
    expect(linesFromQuoteItems([bruto])[0]).toMatchObject({
      quantidade: 3, valorUnitario: 26.7, descontoPercentual: 5,
    });
  });

  it("lista vazia devolve uma linha em branco, nao um formulario sem linhas", () => {
    // Mesmo motivo do `linesFromSaleItems`: o PUT no Bling substitui os itens
    // pelo que estiver no formulário. Abrir a edição sem linha nenhuma e salvar
    // apagaria os itens da proposta no ERP — e um formulário sem linha também
    // não tem como ser usado.
    expect(linesFromQuoteItems([])).toEqual([blankLine()]);
    expect(linesFromQuoteItems(null)).toEqual([blankLine()]);
    expect(linesFromQuoteItems(undefined)).toEqual([blankLine()]);
  });

  it("as linhas carregadas reproduzem o total do orcamento salvo", () => {
    // A prova de que a edição não muda o dinheiro por si só: recarregar os
    // itens e recalcular tem que devolver o mesmo subtotal gravado.
    const linhas = linesFromQuoteItems([
      item({ id: "a", quantidade: 10, desconto_percentual: 0, ordem: 0 }),
      item({ id: "b", bling_product_id: 124, codigo: "CAN-SUA-500",
        descricao: "Cafe Canastra Suave Moido 500g", unidade: "CX",
        quantidade: 2, valor_unitario: 44.9, desconto_percentual: 10, ordem: 1 }),
    ]);
    expect(quoteSubtotal(linhas)).toBe(347.82);
  });
});
