/**
 * `contaTravadaDoOrcamento` decide se o vendedor pode trocar a conta Bling ao
 * editar um orcamento — errar na direcao "liberado" abriria a porta para
 * gravar um orcamento com a conta diferente da proposta comercial que ja
 * existe naquele CNPJ (design secao 7.1). Testado isolado da UI, mesmo padrao
 * de `lib/bling-accounts.test.ts`.
 */
import { describe, expect, it } from "vitest";
import { contaTravadaDoOrcamento } from "./quote-create-modal";
import { CONTA_PADRAO } from "@/lib/bling-accounts";

/**
 * `Quote` tem dezenas de campos obrigatorios que nao importam para esta
 * funcao — ela so le `bling_account` e `bling_proposal_number`. O cast via
 * `unknown` documenta que o fixture e deliberadamente parcial.
 */
type QuoteFixture = Parameters<typeof contaTravadaDoOrcamento>[0];
const orcamento = (campos: {
  bling_account?: string;
  bling_proposal_number?: number;
}): QuoteFixture => campos as unknown as QuoteFixture;

describe("contaTravadaDoOrcamento", () => {
  it("nao trava ao criar um orcamento novo (isEditing false)", () => {
    expect(contaTravadaDoOrcamento(orcamento({ bling_account: "secundaria" }), false)).toBeUndefined();
  });

  it("trava na conta gravada mesmo ANTES de converter em venda — diferente da venda, aqui basta estar editando", () => {
    const q = orcamento({ bling_account: "secundaria", bling_proposal_number: 42 });
    expect(contaTravadaDoOrcamento(q, true)).toEqual({
      valor: "secundaria",
      dica: "Definido pelo orçamento #42",
    });
  });

  it("cai para CONTA_PADRAO quando o orcamento e anterior a migration (bling_account ausente)", () => {
    const q = orcamento({ bling_proposal_number: 7 });
    expect(contaTravadaDoOrcamento(q, true)).toEqual({
      valor: CONTA_PADRAO,
      dica: "Definido pelo orçamento #7",
    });
  });

  it("dica sem numero da proposta nao deixa '#' solto", () => {
    const q = orcamento({ bling_account: CONTA_PADRAO });
    expect(contaTravadaDoOrcamento(q, true)).toEqual({
      valor: CONTA_PADRAO,
      dica: "Definido pelo orçamento",
    });
  });

  it("trava mesmo com editingQuote nulo (defensivo — nao deveria acontecer, mas nao deixa o seletor destravar)", () => {
    expect(contaTravadaDoOrcamento(null, true)).toEqual({
      valor: CONTA_PADRAO,
      dica: "Definido pelo orçamento",
    });
  });
});
