/**
 * @vitest-environment jsdom
 *
 * D7 (cartão 1e6381fe): a receita do /trafego é sem frete, e o frete aparece à parte.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CampaignKpis } from "./campaign-kpis";
import type { CampaignRow } from "./campaign-report-table";

const ROW: CampaignRow = {
  channel: "Google Ads", campaign: "black", leads: 10, conversas: 5, closer: 2, clientes: 1,
  pedidos: 1, receita: 450, frete: 50, investimento: 100, roas: 4.5, ticket_medio: 450, conversao: 0.1,
};

afterEach(cleanup);

describe("CampaignKpis — receita e frete", () => {
  it("mostra a receita com a legenda 'sem frete'", () => {
    render(<CampaignKpis summary={ROW} />);
    const card = screen.getByText("Receita").closest("div[data-kpi]") as HTMLElement;
    expect(card.textContent).toContain("sem frete");
    expect(card.textContent).toContain("R$ 450,00");
  });

  it("mostra o KPI Frete", () => {
    render(<CampaignKpis summary={ROW} />);
    const card = screen.getByText("Frete").closest("div[data-kpi]") as HTMLElement;
    expect(card.textContent).toContain("R$ 50,00");
  });

  it("frete ausente (backend antigo) vira zero", () => {
    const { frete: _omit, ...semFrete } = ROW;
    render(<CampaignKpis summary={semFrete as CampaignRow} />);
    const card = screen.getByText("Frete").closest("div[data-kpi]") as HTMLElement;
    expect(card.textContent).toContain("R$ 0,00");
  });
});
