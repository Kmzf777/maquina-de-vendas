import { describe, expect, it } from "vitest";
import {
  addLine,
  applyProduct,
  blankLine,
  buildOrderPayload,
  defaultPaymentMethodId,
  lineTotal,
  linesFromSaleItems,
  removeLine,
  updateLine,
} from "@/lib/bling-order-state";
import type { SaleItem } from "@/lib/types";

const PRODUTOS = [
  { id: 123, codigo: "CAN-CLA-250", nome: "Cafe Canastra Classico Moido 250g",
    preco: 26.7, unidade: "UN", saldo_virtual: 480 },
  { id: 124, codigo: "CAN-SUA-500", nome: "Cafe Canastra Suave Moido 500g",
    preco: 44.9, unidade: "UN", saldo_virtual: 120 },
];

describe("linhas de item", () => {
  it("comeca com uma linha vazia", () => {
    expect(blankLine()).toMatchObject({
      blingProductId: null, quantidade: 1, valorUnitario: 0, descontoPercentual: 0,
    });
  });

  it("adiciona e remove linhas", () => {
    let linhas = [blankLine()];
    linhas = addLine(linhas);
    expect(linhas).toHaveLength(2);
    linhas = removeLine(linhas, 1);
    expect(linhas).toHaveLength(1);
  });

  it("nunca remove a ultima linha", () => {
    const linhas = removeLine([blankLine()], 0);
    expect(linhas).toHaveLength(1);
  });

  it("escolher o produto preenche preco, descricao, codigo e unidade", () => {
    const linhas = applyProduct([blankLine()], 0, 123, PRODUTOS);
    expect(linhas[0]).toMatchObject({
      blingProductId: 123,
      descricao: "Cafe Canastra Classico Moido 250g",
      codigo: "CAN-CLA-250",
      unidade: "UN",
      valorUnitario: 26.7,
    });
  });

  it("produto desconhecido nao apaga o que ja estava", () => {
    const antes = applyProduct([blankLine()], 0, 123, PRODUTOS);
    const depois = applyProduct(antes, 0, 999, PRODUTOS);
    expect(depois[0].valorUnitario).toBe(26.7);
  });

  it("updateLine mexe so na linha alvo", () => {
    const linhas = updateLine([blankLine(), blankLine()], 1, { quantidade: 10 });
    expect(linhas[0].quantidade).toBe(1);
    expect(linhas[1].quantidade).toBe(10);
  });
});

describe("buildOrderPayload", () => {
  const base = {
    leadId: "L1", dealId: "D1", soldAt: "2026-08-18", soldBy: "v@e.com",
    paymentMethodId: 45, terms: [30, 60], notes: "",
  };

  it("monta o payload da API com total e parcelas", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10 });
    const out = buildOrderPayload(linhas, base);

    expect(out.valid).toBe(true);
    expect(out.total).toBe(267);
    expect(out.payload.items[0]).toMatchObject({
      bling_product_id: 123, quantidade: 10, valor_unitario: 26.7,
    });
    expect(out.payload.payment).toMatchObject({ method_id: 45, terms: [30, 60] });
    expect(out.payload.lead_id).toBe("L1");
    expect(out.installments.map((p) => p.valor)).toEqual([133.5, 133.5]);
    expect(out.installments[0].dataVencimento).toBe("2026-09-17");
  });

  it("invalido sem forma de pagamento", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10 });
    expect(buildOrderPayload(linhas, { ...base, paymentMethodId: null }).valid).toBe(false);
  });

  it("invalido enquanto nenhuma linha tem produto", () => {
    expect(buildOrderPayload([blankLine()], base).valid).toBe(false);
  });

  it("invalido com quantidade zero", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 0 });
    expect(buildOrderPayload(linhas, base).valid).toBe(false);
  });

  it("descarta linhas incompletas do payload", () => {
    let linhas = applyProduct([blankLine()], 0, 123, PRODUTOS);
    linhas = updateLine(linhas, 0, { quantidade: 10 });
    linhas = addLine(linhas); // a segunda linha fica vazia
    const out = buildOrderPayload(linhas, base);
    expect(out.valid).toBe(true);
    expect(out.payload.items).toHaveLength(1);
  });

  it("sem prazo nenhum vira a vista", () => {
    const linhas = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10 });
    const out = buildOrderPayload(linhas, { ...base, terms: [] });
    expect(out.payload.payment.terms).toEqual([0]);
    expect(out.installments).toEqual([
      { dataVencimento: "2026-08-18", valor: 267 },
    ]);
  });
});

// ── extensões usadas pela casca de renderização ────────────────────────────
// O componente não faz aritmética nem escolhe padrão sozinho; chama daqui.

describe("lineTotal", () => {
  it("multiplica e aplica o desconto", () => {
    const linha = updateLine(applyProduct([blankLine()], 0, 123, PRODUTOS), 0,
      { quantidade: 10, descontoPercentual: 10 })[0];
    expect(lineTotal(linha)).toBe(240.3);
  });
  it("linha vazia vale zero", () => {
    expect(lineTotal(blankLine())).toBe(0);
  });
});

describe("linesFromSaleItems", () => {
  const item = (patch: Partial<SaleItem>): SaleItem => ({
    id: "i1", sale_id: "s1", bling_product_id: 123, codigo: "CAN-CLA-250",
    descricao: "Cafe Canastra Classico Moido 250g", quantidade: 2,
    valor_unitario: 26.7, desconto_percentual: 0, total: 53.4, ordem: 0,
    ...patch,
  });

  it("converte item em linha preservando produto, codigo, descricao, quantidade, valor e desconto", () => {
    const linhas = linesFromSaleItems([item({ desconto_percentual: 10 })]);
    expect(linhas).toEqual([{
      blingProductId: 123,
      descricao: "Cafe Canastra Classico Moido 250g",
      codigo: "CAN-CLA-250",
      unidade: null,
      quantidade: 2,
      valorUnitario: 26.7,
      descontoPercentual: 10,
    }]);
  });

  it("respeita a ordem (ordem), mesmo que os itens cheguem fora de ordem", () => {
    const linhas = linesFromSaleItems([
      item({ id: "b", descricao: "Segundo", ordem: 1 }),
      item({ id: "a", descricao: "Primeiro", ordem: 0 }),
    ]);
    expect(linhas.map((l) => l.descricao)).toEqual(["Primeiro", "Segundo"]);
  });

  it("lista vazia devolve uma linha em branco, nao um formulario sem linhas", () => {
    expect(linesFromSaleItems([])).toEqual([blankLine()]);
  });

  it("undefined/null tambem devolvem uma linha em branco", () => {
    expect(linesFromSaleItems(undefined)).toEqual([blankLine()]);
    expect(linesFromSaleItems(null)).toEqual([blankLine()]);
  });
});

describe("defaultPaymentMethodId", () => {
  it("usa a forma marcada como padrao no Bling", () => {
    expect(defaultPaymentMethodId([
      { id: 1, descricao: "Dinheiro", padrao: 0 },
      { id: 45, descricao: "Boleto", padrao: 1 },
    ])).toBe(45);
  });
  it("com uma unica forma nao ha o que perguntar", () => {
    expect(defaultPaymentMethodId([{ id: 7, descricao: "Pix" }])).toBe(7);
  });
  it("varias sem padrao exige escolha do vendedor", () => {
    expect(defaultPaymentMethodId([
      { id: 1, descricao: "Dinheiro" },
      { id: 2, descricao: "Pix" },
    ])).toBeNull();
  });
  it("lista vazia nao inventa forma", () => {
    expect(defaultPaymentMethodId([])).toBeNull();
  });
});
