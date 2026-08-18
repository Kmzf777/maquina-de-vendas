import { describe, expect, it } from "vitest";
import {
  buildInstallments,
  itemTotal,
  orderTotal,
  parseTerms,
  productSummary,
} from "@/lib/bling";

describe("parseTerms", () => {
  it("interpreta a condicao do Bling", () => {
    expect(parseTerms("30/60/90")).toEqual([30, 60, 90]);
    expect(parseTerms("30")).toEqual([30]);
    expect(parseTerms("")).toEqual([0]);
    expect(parseTerms("a vista")).toEqual([0]);
  });
});

describe("itemTotal", () => {
  it("aplica desconto percentual", () => {
    expect(itemTotal({ quantidade: 10, valorUnitario: 26.7, descontoPercentual: 10 }))
      .toBe(240.3);
  });
  it("sem desconto multiplica direto", () => {
    expect(itemTotal({ quantidade: 3, valorUnitario: 50, descontoPercentual: 0 }))
      .toBe(150);
  });
});

describe("orderTotal", () => {
  it("soma os itens", () => {
    expect(orderTotal([
      { quantidade: 10, valorUnitario: 26.7, descontoPercentual: 0 },
      { quantidade: 2, valorUnitario: 50, descontoPercentual: 0 },
    ])).toBe(367);
  });
  it("pedido vazio vale zero", () => {
    expect(orderTotal([])).toBe(0);
  });
});

describe("buildInstallments", () => {
  it("a vista gera uma parcela na data da venda", () => {
    expect(buildInstallments(500, [0], "2026-08-18")).toEqual([
      { dataVencimento: "2026-08-18", valor: 500 },
    ]);
  });

  it("30/60 divide em duas e soma os dias", () => {
    const p = buildInstallments(500, [30, 60], "2026-08-18");
    expect(p.map((x) => x.dataVencimento)).toEqual(["2026-09-17", "2026-10-17"]);
    expect(p.map((x) => x.valor)).toEqual([250, 250]);
  });

  it("a ultima parcela absorve o arredondamento", () => {
    // Precisa bater com o backend: 100,00 em 3x = 33,33 + 33,33 + 33,34.
    const p = buildInstallments(100, [30, 60, 90], "2026-08-18");
    expect(p.map((x) => x.valor)).toEqual([33.33, 33.33, 33.34]);
    const soma = p.reduce((acc, x) => acc + x.valor, 0);
    expect(Math.round(soma * 100) / 100).toBe(100);
  });

  it("usa arredondamento half-up, nao floor — paridade com o backend", () => {
    // ESTE TESTE EXISTE PARA IMPEDIR UMA "SIMPLIFICACAO" ESPECIFICA.
    // Trocar Math.round por Math.floor no calculo de `base` parece inofensivo e
    // a soma continua fechando — mas divide diferente em 46,7% dos totais
    // realistas (medido em ~1M de combinacoes de R$1 a R$2.000). O backend usa
    // Decimal com ROUND_HALF_UP; com floor, o vendedor veria na tela uma divisao
    // diferente da que foi gravada no ERP, e sem erro nenhum para denunciar.
    //
    // R$10,01 em 2x: half-up da [5.01, 5.00]; floor daria [5.00, 5.01].
    expect(buildInstallments(10.01, [0, 30], "2026-08-18").map((x) => x.valor))
      .toEqual([5.01, 5.0]);
    // R$10,00 em 6x: half-up da 1.67 x5 + 1.65; floor daria 1.66 x5 + 1.70.
    expect(buildInstallments(10, [0, 30, 60, 90, 120, 150], "2026-08-18")
      .map((x) => x.valor)).toEqual([1.67, 1.67, 1.67, 1.67, 1.67, 1.65]);
  });

  it("a ultima parcela pode ser MENOR que as demais", () => {
    // Consequencia do half-up que contraria a leitura literal de "a ultima
    // absorve o resto". O espelho TS precisa reproduzir isso, nao "consertar".
    const p = buildInstallments(10, [0, 30, 60, 90, 120, 150], "2026-08-18");
    expect(p[p.length - 1].valor).toBeLessThan(p[0].valor);
  });

  it("nunca deixa centavo sobrando", () => {
    for (const total of [10, 99.99, 1234.56, 0.03]) {
      const p = buildInstallments(total, [0, 30, 60], "2026-08-18");
      const soma = p.reduce((acc, x) => acc + x.valor, 0);
      expect(Math.round(soma * 100) / 100).toBe(total);
    }
  });
});

describe("productSummary", () => {
  it("um item usa a descricao", () => {
    expect(productSummary([{ descricao: "Cafe 250g" }])).toBe("Cafe 250g");
  });
  it("varios itens somam o contador", () => {
    expect(productSummary([
      { descricao: "Cafe 250g" }, { descricao: "Cafe 500g" }, { descricao: "Drip" },
    ])).toBe("Cafe 250g +2 itens");
  });
});
