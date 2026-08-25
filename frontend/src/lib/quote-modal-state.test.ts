import { describe, expect, it } from "vitest";
import type { OrderPayloadResult } from "@/lib/bling-order-state";
import {
  FREIGHT_MODES,
  discountFromQuote,
  formatQuoteDate,
  linesFromOrderPayload,
  parseDecimalInput,
  quoteNumberLabel,
  quotePdfHref,
  quoteOwner,
  quoteRequest,
  quoteSaveOutcome,
  quoteStatusView,
} from "@/lib/quote-modal-state";

describe("quoteRequest", () => {
  it("cria com POST em /api/quotes", () => {
    expect(quoteRequest(null)).toEqual({ url: "/api/quotes", method: "POST" });
    expect(quoteRequest(undefined)).toEqual({ url: "/api/quotes", method: "POST" });
  });

  it("edita com PUT no id do orcamento", () => {
    expect(quoteRequest({ id: "Q1" })).toEqual({
      url: "/api/quotes/Q1",
      method: "PUT",
    });
  });
});

describe("discountFromQuote", () => {
  it("reexibe a UNIDADE e o NUMERO digitados, nao o valor ja convertido", () => {
    // O caso concreto: 10% sobre R$267,00 grava discount_value=26,70 e
    // discount_input=10. Reabrir mostrando 26,70 faria o vendedor achar que o
    // sistema trocou o desconto dele.
    expect(
      discountFromQuote({ discount_unit: "PERCENTUAL", discount_input: 10 }),
    ).toEqual({ valor: 10, unidade: "PERCENTUAL" });
  });

  it("mantem REAL como REAL", () => {
    expect(discountFromQuote({ discount_unit: "REAL", discount_input: 26.7 })).toEqual({
      valor: 26.7,
      unidade: "REAL",
    });
  });

  it("sem desconto devolve nulo — zero e negativo nao viram campo preenchido", () => {
    expect(discountFromQuote(null)).toBeNull();
    expect(discountFromQuote(undefined)).toBeNull();
    expect(discountFromQuote({ discount_unit: "REAL", discount_input: 0 })).toBeNull();
    expect(discountFromQuote({ discount_unit: "REAL", discount_input: -5 })).toBeNull();
  });

  it("aceita numeric vindo como string do PostgREST", () => {
    expect(
      discountFromQuote({
        discount_unit: "PERCENTUAL",
        discount_input: "12.5" as unknown as number,
      }),
    ).toEqual({ valor: 12.5, unidade: "PERCENTUAL" });
  });
});

describe("quoteOwner", () => {
  it("na criacao o dono e quem esta logado", () => {
    expect(quoteOwner(null, "vendedor@cafecanastra.com")).toBe(
      "vendedor@cafecanastra.com",
    );
  });

  it("na edicao o dono continua sendo quem criou", () => {
    // O escopo por vendedor filtra por `created_by`: gravar o e-mail de quem
    // edita faria o orcamento sumir da lista do vendedor assim que um admin
    // abrisse a tela para corrigir um frete.
    expect(
      quoteOwner({ created_by: "vendedor@x.com" }, "admin@x.com"),
    ).toBe("vendedor@x.com");
  });

  it("orcamento sem dono adota quem esta editando", () => {
    expect(quoteOwner({ created_by: null }, "admin@x.com")).toBe("admin@x.com");
    expect(quoteOwner({ created_by: "" }, "admin@x.com")).toBe("admin@x.com");
  });

  it("sem ninguem identificado devolve nulo, nunca string vazia", () => {
    expect(quoteOwner(null, "")).toBeNull();
    expect(quoteOwner(null, undefined)).toBeNull();
  });
});

describe("linesFromOrderPayload", () => {
  const resultado = (
    items: OrderPayloadResult["payload"]["items"],
  ): OrderPayloadResult => ({
    valid: true,
    total: 0,
    installments: [],
    payload: {
      lead_id: "L1",
      deal_id: null,
      sold_at: "2026-08-25",
      sold_by: null,
      notes: "",
      items,
      payment: { method_id: 45, terms: [30] },
    },
  });

  it("traduz o item do pedido para linha, INCLUSIVE a unidade", () => {
    // A unidade e o campo que se perde com facilidade nessa traducao: o item da
    // proposta comercial a envia para o Bling, e `sale_items` nem a guarda.
    const linhas = linesFromOrderPayload(
      resultado([
        {
          bling_product_id: 123,
          codigo: "CAN-CLA-250",
          descricao: "Cafe Canastra Classico 250g",
          unidade: "CX",
          quantidade: 3,
          valor_unitario: 26.7,
          desconto_percentual: 5,
        },
      ]),
    );
    expect(linhas).toEqual([
      {
        blingProductId: 123,
        codigo: "CAN-CLA-250",
        descricao: "Cafe Canastra Classico 250g",
        unidade: "CX",
        quantidade: 3,
        valorUnitario: 26.7,
        descontoPercentual: 5,
      },
    ]);
  });

  it("sem resultado ainda devolve lista vazia — nunca quebra o resumo", () => {
    expect(linesFromOrderPayload(null)).toEqual([]);
    expect(linesFromOrderPayload(undefined)).toEqual([]);
  });
});

describe("quoteSaveOutcome", () => {
  it("201 devolve o que o vendedor procura: numero da proposta e total", () => {
    expect(
      quoteSaveOutcome(201, {
        id: "Q1",
        bling_proposal_id: 99,
        bling_proposal_number: 13,
        total: 1234.5,
      }),
    ).toEqual({ kind: "saved", id: "Q1", numero: 13, total: 1234.5 });
  });

  it("200 do PUT nao traz numero — e isso nao e erro", () => {
    expect(quoteSaveOutcome(200, { id: "Q1", total: 10 })).toEqual({
      kind: "saved",
      id: "Q1",
      numero: null,
      total: 10,
    });
  });

  it("201 sem numero (o GET seguinte falhou no backend) ainda e sucesso", () => {
    expect(
      quoteSaveOutcome(201, { id: "Q1", bling_proposal_id: 99, total: 10 }),
    ).toEqual({ kind: "saved", id: "Q1", numero: null, total: 10 });
  });

  it("409 de contato abre o resolvedor, com os candidatos", () => {
    expect(
      quoteSaveOutcome(409, {
        error: "contact_unresolved",
        status: "ambiguous",
        reason: "documento_duplicado",
        candidates: [{ id: 1, nome: "Padaria Central" }],
      }),
    ).toEqual({
      kind: "contact",
      status: "ambiguous",
      reason: "documento_duplicado",
      candidates: [{ id: 1, nome: "Padaria Central" }],
    });
  });

  it("409 de orcamento convertido NAO e contato — sao o mesmo codigo HTTP", () => {
    // A distincao vive so no campo `error`. Confundir os dois abriria o
    // resolvedor de contato vazio para um orcamento que ja virou venda, e o
    // vendedor ficaria cadastrando cliente para um PUT que nunca vai passar.
    expect(quoteSaveOutcome(409, { error: "quote_converted" })).toEqual({
      kind: "converted",
    });
  });

  it("409 desconhecido vira erro legivel, nao resolvedor de contato", () => {
    const out = quoteSaveOutcome(409, { error: "outra_coisa" });
    expect(out.kind).toBe("error");
  });

  it("422 preserva a mensagem original do Bling — e ela que diz o que corrigir", () => {
    expect(
      quoteSaveOutcome(422, {
        message: "Campo obrigatorio.",
        detail: "parcelas[0].valor",
      }),
    ).toEqual({ kind: "error", message: "Campo obrigatorio. parcelas[0].valor" });
  });

  it("corpo vazio ainda produz mensagem com o codigo HTTP", () => {
    const out = quoteSaveOutcome(500, {});
    expect(out.kind).toBe("error");
    expect(out.kind === "error" && out.message).toContain("500");
  });
});

describe("parseDecimalInput", () => {
  it("aceita virgula como separador decimal (pt-BR)", () => {
    expect(parseDecimalInput("12,5")).toBe(12.5);
    expect(parseDecimalInput("0,05")).toBe(0.05);
  });

  it("aceita ponto como separador decimal", () => {
    expect(parseDecimalInput("12.5")).toBe(12.5);
  });

  it("descarta o ponto de milhar quando ha virgula decimal", () => {
    // "1.250,00" digitado inteiro daria NaN -> 0 no parse ingenuo, e o frete
    // sumiria em silencio do total.
    expect(parseDecimalInput("1.250,00")).toBe(1250);
    expect(parseDecimalInput("12.345,67")).toBe(12345.67);
  });

  it("vazio, lixo e negativo viram zero", () => {
    expect(parseDecimalInput("")).toBe(0);
    expect(parseDecimalInput("   ")).toBe(0);
    expect(parseDecimalInput("abc")).toBe(0);
    expect(parseDecimalInput("-10")).toBe(0);
  });
});

describe("quoteStatusView", () => {
  it("traduz a situacao para o rotulo que o vendedor le", () => {
    expect(quoteStatusView("rascunho").label).toBe("Rascunho");
    expect(quoteStatusView("nao_aprovado").label).toBe("Não aprovado");
    expect(quoteStatusView("convertido").label).toBe("Convertido em venda");
  });

  it("situacao desconhecida nao apaga o badge", () => {
    // Uma situacao nova no banco (migration futura) nao pode deixar a linha do
    // orcamento com um espaco em branco no lugar da situacao.
    const view = quoteStatusView("situacao_nova");
    expect(view.label).toBe("situacao_nova");
    expect(view.dot).toBeTruthy();
  });
});

describe("quoteNumberLabel e quotePdfHref", () => {
  it("mostra o numero da proposta quando o Bling ja devolveu", () => {
    expect(quoteNumberLabel({ bling_proposal_number: 13 })).toBe("#13");
  });

  it("sem numero nao inventa um — o GET do numero e best-effort no backend", () => {
    expect(quoteNumberLabel({ bling_proposal_number: null })).toBe("sem nº");
  });

  it("o PDF e sempre pelo id do orcamento, que existe mesmo sem numero", () => {
    expect(quotePdfHref("Q1")).toBe("/api/quotes/Q1/pdf");
  });
});

describe("formatQuoteDate", () => {
  it("mostra o dia certo — `quoted_at` e uma coluna date, nao um instante", () => {
    // new Date("2026-08-25").toLocaleDateString("pt-BR") daria 24/08 em BRT.
    expect(formatQuoteDate("2026-08-25")).toBe("25/08/2026");
    expect(formatQuoteDate("2026-01-01")).toBe("01/01/2026");
  });

  it("aceita timestamp completo, cortando a hora", () => {
    expect(formatQuoteDate("2026-08-25T03:00:00Z")).toBe("25/08/2026");
  });

  it("valor ausente ou invalido nao imprime NaN na tela", () => {
    expect(formatQuoteDate(null)).toBe("—");
    expect(formatQuoteDate("")).toBe("—");
    expect(formatQuoteDate("qualquer coisa")).toBe("—");
  });
});

describe("FREIGHT_MODES", () => {
  it("carrega os codigos exatos que o Bling aceita em freteModalidade", () => {
    expect(FREIGHT_MODES.map((m) => m.value)).toEqual([0, 1, 2, 3, 4, 9]);
  });
});
