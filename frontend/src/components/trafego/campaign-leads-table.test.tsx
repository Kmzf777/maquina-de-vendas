/**
 * @vitest-environment jsdom
 *
 * Colunas da call de 01/10 (P2): "Já era cliente" (com selo auto), "Compras" e "Primeira
 * origem" (vazia → canal atual marcado "(atual)"), mais o selo "manual" no nome.
 * Sem jest-dom (não é dependência do projeto): asserções com a API crua do DOM.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  CampaignLeadsTable, jaEraClienteTexto, primeiraOrigemTexto, type CampaignLead,
} from "./campaign-leads-table";

const base: CampaignLead = {
  lead_id: "x", name: "X", phone: null, created_at: "2026-09-01T12:00:00Z",
  utm_source: null, utm_medium: null, utm_campaign: null, traffic_type: null,
  conversou: false, stage: null, comprou: false, valor: 0, sold_at: null,
};

const LEADS: CampaignLead[] = [
  {
    ...base, lead_id: "a", name: "Iago", canal: "Google Ads", ja_era_cliente: true,
    ja_era_cliente_fonte: "auto", compras: 2,
    primeira_origem: { canal: "Meta Ads", campanha_id: "cm", campanha_nome: "Atacado WA", occurred_at: null },
  },
  { ...base, lead_id: "b", name: "Velho Hank", canal: "Google Ads", ja_era_cliente: null, compras: 0, primeira_origem: null },
  {
    ...base, lead_id: "c", name: "Serginho", canal: "Meta Ads", ja_era_cliente: false,
    ja_era_cliente_fonte: "vendedor", compras: 1, atribuicao_manual: true,
  },
];

const linha = (nome: string) => screen.getByText(nome).closest("tr") as HTMLElement;
// "Conversou" também escreve Sim/Não: lê a célula pela posição do cabeçalho.
const celula = (row: HTMLElement, coluna: string) => {
  const idx = screen.getAllByRole("columnheader").findIndex((th) => th.textContent === coluna);
  return row.querySelectorAll("td")[idx] as HTMLElement;
};

afterEach(cleanup);

describe("helpers", () => {
  it("jaEraClienteTexto: Sim / Não / —", () => {
    expect([true, false, null, undefined].map(jaEraClienteTexto)).toEqual(["Sim", "Não", "—", "—"]);
  });
  it("primeiraOrigemTexto: origem registrada, senão canal atual", () => {
    expect(primeiraOrigemTexto(LEADS[0])).toEqual({ texto: "Meta Ads · Atacado WA", atual: false });
    expect(primeiraOrigemTexto(LEADS[1])).toEqual({ texto: "Google Ads", atual: true });
    expect(primeiraOrigemTexto({ canal: null, primeira_origem: null })).toEqual({ texto: "—", atual: false });
  });
});

describe("CampaignLeadsTable", () => {
  it("tem as colunas novas no cabeçalho", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const cabecalho = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(cabecalho).toEqual(expect.arrayContaining(["Já era cliente", "Compras", "Primeira origem"]));
  });

  it("mostra Sim com selo auto, compras e primeira origem", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Iago");
    expect(within(celula(row, "Já era cliente")).getByText("Sim")).toBeTruthy();
    expect(within(row).getByText("auto")).toBeTruthy();
    expect(celula(row, "Compras").textContent).toBe("2");
    expect(within(row).getByText("Meta Ads · Atacado WA")).toBeTruthy();
  });

  it("sem primeira origem cai no canal atual com (atual), e desconhecido é —", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Velho Hank");
    expect(within(row).getByText("Google Ads (atual)")).toBeTruthy();
    expect(celula(row, "Já era cliente").textContent).toBe("—");
    expect(within(row).queryByText("auto")).toBeNull();
  });

  it("resposta do vendedor não ganha selo auto; atribuição manual ganha selo manual", () => {
    render(<CampaignLeadsTable leads={LEADS} />);
    const row = linha("Serginho");
    expect(within(celula(row, "Já era cliente")).getByText("Não")).toBeTruthy();
    expect(within(row).queryByText("auto")).toBeNull();
    expect(within(row).getByText("manual")).toBeTruthy();
  });
});
