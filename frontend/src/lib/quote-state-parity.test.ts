/* ═══════════════════════════════════════════════════════════════════════════
 * CONTRATO DE PARIDADE — orçamento: desconto, total e parcelas
 * ───────────────────────────────────────────────────────────────────────────
 * ESTA TABELA É COPIADA LITERALMENTE PARA `backend/tests/test_quotes_total.py`
 * (e `test_quotes_discount.py`). Os mesmos números, os mesmos casos.
 *
 * Por quê: o vendedor vê o desconto, o total e as parcelas na tela ANTES de
 * salvar, e o backend recalcula tudo do zero para montar o payload do Bling. Se
 * as duas contas divergirem em um centavo, ou o Bling recusa a proposta (a soma
 * das parcelas tem que fechar com o total) ou — pior — aceita um número
 * diferente do que foi prometido ao cliente, sem erro nenhum para denunciar.
 * É a mesma disciplina que `bling.ts` já documenta para o pedido de venda.
 *
 * Regras que os dois lados implementam:
 *   resolveDiscount(subtotal, {valor, unidade})
 *     PERCENTUAL -> subtotal * valor / 100 ; REAL -> valor
 *     arredonda em centavo com HALF_UP; satura no subtotal; valor <= 0 -> 0
 *   quoteTotal(subtotal, desconto, frete) = subtotal - desconto + frete
 *     (o frete ENTRA no total e é parcelado junto — é o que o cliente paga)
 *   buildInstallments(total, prazos) — a última parcela absorve o resto
 *
 * O valor digitado — em % ou em R$ — é tratado com no máximo 3 casas decimais
 * dos dois lados, porque é o que `quotes.discount_input numeric(12,3)` guarda:
 * uma quarta casa não sobreviveria ao INSERT e não pode mudar o total exibido na
 * tela. O frontend já manda o número normalizado nessas 3 casas no payload, de
 * modo que o backend recalcula a partir EXATAMENTE do valor que a tela usou.
 *
 *  #  | subtotal | desconto        | = desconto R$ | frete  | = total  | prazos               | parcelas
 * ----|----------|-----------------|---------------|--------|----------|----------------------|-----------------------------------
 *  P1 |   100,00 | 33%             |        33,00  |   0,00 |    67,00 | [0]                  | 67,00
 *  P2 |    10,01 | 50%             |         5,01  |   0,00 |     5,00 | [0]                  | 5,00
 *  P3 |    89,90 | 12,5%           |        11,24  |   0,00 |    78,66 | [30,60]              | 39,33 · 39,33
 *  P4 | 3.525,00 | 23,58%          |       831,20  |   0,00 | 2.693,80 | [30,60,90]           | 897,93 · 897,93 · 897,94
 *  P5 |    80,10 | 7,5%            |         6,01  |   0,00 |    74,09 | [30,60]              | 37,05 · 37,04
 *  P6 |   120,00 | 150%            |       120,00  |   0,00 |     0,00 | [0]                  | (recusado: sem centavo a dividir)
 *  R1 |   267,00 | R$ 26,70        |        26,70  |  35,50 |   275,80 | [30,60]              | 137,90 · 137,90
 *  R2 |   100,00 | R$ 16,025       |        16,03  |   0,00 |    83,97 | [0]                  | 83,97
 *  R3 |    50,00 | R$ 80,00        |        50,00  |  12,00 |    12,00 | [0]                  | 12,00
 *  Z1 |    42,00 | (sem desconto)  |         0,00  |   0,00 |    42,00 | [0]                  | 42,00
 *  Z2 |    42,00 | R$ -5,00        |         0,00  |   0,00 |    42,00 | [0]                  | 42,00
 *  F1 |    70,00 | (sem desconto)  |         0,00  |  30,00 |   100,00 | [0,30,60]            | 33,33 · 33,33 · 33,34
 *  F2 |     8,00 | (sem desconto)  |         0,00  |   2,00 |    10,00 | [0,30,60,90,120,150] | 1,67 ×5 · 1,65
 *  F3 |   200,00 | 33%             |        66,00  |  15,90 |   149,90 | [30,60,90]           | 49,97 · 49,97 · 49,96
 *
 * O que cada caso guarda (não são números aleatórios):
 *   P2, P3, P5  meio centavo exato — 5,005 / 11,2375 / 6,0075. HALF_UP arredonda
 *               PARA CIMA nos dois lados; truncar daria um centavo a menos.
 *   P4          REGRESSÃO DE FLOAT. 3525,00 × 23,58% = 831,20 no Decimal, mas
 *               `Math.round(352500 * 23.58 / 100)` em JS dá 831,19 — o produto
 *               em float cai em 83119,49999999999. Por isso o TS multiplica o
 *               percentual em MILÉSIMOS inteiros antes de dividir. Medido: 1 em
 *               200.000 combinações erra pela via ingênua, 0 em 700.000 pela via
 *               inteira.
 *   P6, R3      saturação: o desconto nunca passa do subtotal. Em P6 o total
 *               zera e NÃO há parcela possível (o backend responde 422); em R3
 *               sobra o frete, que não é descontável.
 *   R2          REGRESSÃO DE FLOAT em REAL: `Math.round(16.025 * 100)` dá 1602
 *               (R$16,02), porque 16,025 × 100 em binário é 1602,4999999999998;
 *               o Decimal dá 16,03. Vale para 218 dos 40.000 valores de três
 *               casas entre R$10 e R$50 — não é uma raridade teórica.
 *   Z1, Z2      ausência e valor negativo viram zero, nunca crédito.
 *   F1, F2, F3  o frete compõe o total ANTES do parcelamento. F1 é o clássico
 *               100,00 em 3x (33,33 · 33,33 · 33,34); em F2 a última parcela é
 *               MENOR que as demais (half-up na base), o que é o comportamento
 *               correto e não um bug a "consertar"; F3 tem dízima na divisão
 *               (149,90 / 3 = 49,9666…).
 * ═══════════════════════════════════════════════════════════════════════════ */
import { describe, expect, it } from "vitest";
import { buildInstallments } from "@/lib/bling";
import { quoteTotal, resolveDiscount, type QuoteDiscount } from "@/lib/quote-state";

interface ParityCase {
  nome: string;
  subtotal: number;
  desconto: QuoteDiscount | null;
  descontoEmReais: number;
  frete: number;
  total: number;
  prazos: number[];
  /** `null` = divisão impossível: o backend levanta 422 e o TS devolve []. */
  parcelas: number[] | null;
}

const CASOS: ParityCase[] = [
  { nome: "P1", subtotal: 100.0, desconto: { valor: 33, unidade: "PERCENTUAL" },
    descontoEmReais: 33.0, frete: 0, total: 67.0, prazos: [0], parcelas: [67.0] },
  { nome: "P2", subtotal: 10.01, desconto: { valor: 50, unidade: "PERCENTUAL" },
    descontoEmReais: 5.01, frete: 0, total: 5.0, prazos: [0], parcelas: [5.0] },
  { nome: "P3", subtotal: 89.9, desconto: { valor: 12.5, unidade: "PERCENTUAL" },
    descontoEmReais: 11.24, frete: 0, total: 78.66, prazos: [30, 60],
    parcelas: [39.33, 39.33] },
  { nome: "P4", subtotal: 3525.0, desconto: { valor: 23.58, unidade: "PERCENTUAL" },
    descontoEmReais: 831.2, frete: 0, total: 2693.8, prazos: [30, 60, 90],
    parcelas: [897.93, 897.93, 897.94] },
  { nome: "P5", subtotal: 80.1, desconto: { valor: 7.5, unidade: "PERCENTUAL" },
    descontoEmReais: 6.01, frete: 0, total: 74.09, prazos: [30, 60],
    parcelas: [37.05, 37.04] },
  { nome: "P6", subtotal: 120.0, desconto: { valor: 150, unidade: "PERCENTUAL" },
    descontoEmReais: 120.0, frete: 0, total: 0.0, prazos: [0], parcelas: null },
  { nome: "R1", subtotal: 267.0, desconto: { valor: 26.7, unidade: "REAL" },
    descontoEmReais: 26.7, frete: 35.5, total: 275.8, prazos: [30, 60],
    parcelas: [137.9, 137.9] },
  { nome: "R2", subtotal: 100.0, desconto: { valor: 16.025, unidade: "REAL" },
    descontoEmReais: 16.03, frete: 0, total: 83.97, prazos: [0], parcelas: [83.97] },
  { nome: "R3", subtotal: 50.0, desconto: { valor: 80, unidade: "REAL" },
    descontoEmReais: 50.0, frete: 12.0, total: 12.0, prazos: [0], parcelas: [12.0] },
  { nome: "Z1", subtotal: 42.0, desconto: null,
    descontoEmReais: 0.0, frete: 0, total: 42.0, prazos: [0], parcelas: [42.0] },
  { nome: "Z2", subtotal: 42.0, desconto: { valor: -5, unidade: "REAL" },
    descontoEmReais: 0.0, frete: 0, total: 42.0, prazos: [0], parcelas: [42.0] },
  { nome: "F1", subtotal: 70.0, desconto: null,
    descontoEmReais: 0.0, frete: 30.0, total: 100.0, prazos: [0, 30, 60],
    parcelas: [33.33, 33.33, 33.34] },
  { nome: "F2", subtotal: 8.0, desconto: null,
    descontoEmReais: 0.0, frete: 2.0, total: 10.0, prazos: [0, 30, 60, 90, 120, 150],
    parcelas: [1.67, 1.67, 1.67, 1.67, 1.67, 1.65] },
  { nome: "F3", subtotal: 200.0, desconto: { valor: 33, unidade: "PERCENTUAL" },
    descontoEmReais: 66.0, frete: 15.9, total: 149.9, prazos: [30, 60, 90],
    parcelas: [49.97, 49.97, 49.96] },
];

const QUOTED_AT = "2026-08-25";

describe("paridade com o backend — resolveDiscount", () => {
  for (const c of CASOS) {
    it(`${c.nome}: desconto de ${c.subtotal} = ${c.descontoEmReais}`, () => {
      expect(resolveDiscount(c.subtotal, c.desconto)).toBe(c.descontoEmReais);
    });
  }
});

describe("paridade com o backend — quoteTotal", () => {
  for (const c of CASOS) {
    it(`${c.nome}: total = ${c.total}`, () => {
      expect(quoteTotal(c.subtotal, c.descontoEmReais, c.frete)).toBe(c.total);
    });
  }

  it("a cadeia inteira (desconto -> total) fecha em todos os casos", () => {
    // Cada função foi conferida isolada acima; aqui a composição, que é como o
    // `buildQuotePayload` usa — para nenhum caso passar por sorte de tabela.
    for (const c of CASOS) {
      const desconto = resolveDiscount(c.subtotal, c.desconto);
      expect(quoteTotal(c.subtotal, desconto, c.frete)).toBe(c.total);
    }
  });
});

describe("paridade com o backend — parcelas sobre o total COM frete", () => {
  for (const c of CASOS) {
    it(`${c.nome}: ${c.prazos.length}x de ${c.total}`, () => {
      const parcelas = buildInstallments(c.total, c.prazos, QUOTED_AT);
      if (c.parcelas === null) {
        // Sem centavo para dividir. O backend recusa com 422 ("alguma parcela
        // ficaria sem valor") e o TS devolve lista vazia — o resumo mostra
        // nada em vez de uma parcela de R$ 0,00.
        expect(parcelas).toEqual([]);
        return;
      }
      expect(parcelas.map((p) => p.valor)).toEqual(c.parcelas);
      // A soma tem que fechar EXATAMENTE com o total: um centavo sobrando é
      // recusa do Bling.
      const soma = parcelas.reduce((acc, p) => acc + p.valor, 0);
      expect(Math.round(soma * 100) / 100).toBe(c.total);
    });
  }
});

describe("paridade com o backend — as armadilhas de float, isoladas", () => {
  it("P4: 23,58% de 3.525,00 e 831,20, nao 831,19", () => {
    // `Math.round(352500 * 23.58 / 100)` = 83119 (o produto em float dá
    // 8311949.999999999). Com o percentual em milésimos inteiros:
    // 352500 * 23580 / 100000 = 83120 exato.
    expect(resolveDiscount(3525, { valor: 23.58, unidade: "PERCENTUAL" })).toBe(831.2);
    expect(Math.round((352500 * 23.58) / 100)).toBe(83119); // a via ingênua erra
  });

  it("R2: R$ 16,025 de desconto e 16,03, nao 16,02", () => {
    // `Math.round(16.025 * 100)` = 1602 porque o produto em float é
    // 1602,4999999999998; `Decimal("16.025").quantize(HALF_UP)` = 16,03.
    // Passando por milésimos inteiros (16025 / 10 = 1602,5, exato em binário)
    // o JS também sobe para 1603.
    expect(resolveDiscount(100, { valor: 16.025, unidade: "REAL" })).toBe(16.03);
    expect(Math.round(16.025 * 100)).toBe(1602); // a via ingênua erra
  });

  it("o desconto percentual sempre fecha em centavo inteiro e nunca passa do subtotal", () => {
    // Varredura: subtotais de R$0,01 a R$1.000,00 contra percentuais de 0,5 em
    // 0,5. O que se procura é resíduo de float — um resultado tipo 26,700000004,
    // que passaria despercebido na tela e viraria divergência no INSERT.
    // As falhas são acumuladas e conferidas de uma vez: é ~100x mais rápido que
    // um `expect` por iteração, e o erro mostra o par exato que quebrou.
    const falhas: string[] = [];
    for (let centavosDoSubtotal = 1; centavosDoSubtotal <= 100000; centavosDoSubtotal += 137) {
      const subtotal = centavosDoSubtotal / 100;
      for (let pct = 0.5; pct <= 100; pct += 0.5) {
        const d = resolveDiscount(subtotal, { valor: pct, unidade: "PERCENTUAL" });
        const residuo = Math.abs(d * 100 - Math.round(d * 100));
        if (residuo > 1e-9 || d > subtotal || d < 0) {
          falhas.push(`${subtotal} @ ${pct}% -> ${d}`);
        }
      }
    }
    expect(falhas).toEqual([]);
  });
});
