/**
 * @vitest-environment jsdom
 *
 * D7 (cartão 1e6381fe) no painel do lead em /trafego: cada venda do card "Vendas" aparece
 * sem frete; a cancelada continua na lista, com o valor sem frete e o selo "cancelada"; o
 * total (Receita) e o ticket não somam cancelada nem frete.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { CampaignLeadPanel, type CampaignLeadPanelTarget } from "./campaign-lead-panel";
import type { LeadOverview, OverviewSale } from "@/lib/lead-overview";

const venda = (o: Partial<OverviewSale> & Pick<OverviewSale, "id" | "value">): OverviewSale => ({
  freight: null, product: null, sold_at: "2026-10-10T15:00:00Z", sold_by: null, origin: null, status: null,
  ...o,
});

const PAYLOAD: LeadOverview = {
  lead: {
    id: "L1", name: "Maria", phone: "5534999999999", company: null, email: null, stage: "cliente",
    segmento: null, status: null, channel: null, assigned_to: null, created_at: "2026-10-01T12:00:00Z",
    last_msg_at: null, last_customer_message_at: null, first_response_at: null, entered_stage_at: null,
    utm_source: null, utm_medium: null, utm_campaign: null, traffic_type: null, notes: null,
  },
  deals: [],
  sales: [
    venda({ id: "s1", value: 1100, freight: 100, product: "Queijo Canastra" }),
    venda({ id: "s2", value: 550, freight: 50, product: "Doce de leite", status: "cancelada" }),
    venda({ id: "s3", value: 300, freight: null, product: "Requeijão" }),
  ],
  events: [],
  notes: [],
  messages: { total: 0, inbound: 0, outbound: 0, first_inbound_at: null, last_at: null },
  cadences: [],
  broadcasts: [],
  followups: [],
};

const TARGET: CampaignLeadPanelTarget = {
  lead_id: "L1", name: "Maria", phone: "5534999999999", traffic_type: null,
  utm_source: null, utm_medium: null, utm_campaign: null,
};

function mockFetch() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url === "/api/leads/L1/overview" ? PAYLOAD : { campanhas: [] };
    return { ok: true, status: 200, json: async () => body };
  }));
}

/** O <div> do card/stat que contém o rótulo. */
const blocoDe = (rotulo: HTMLElement) => rotulo.parentElement as HTMLElement;

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CampaignLeadPanel — vendas pela D7", () => {
  it("card Vendas mostra cada venda sem frete e marca a cancelada", async () => {
    mockFetch();
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    const card = blocoDe(await screen.findByText("Vendas"));
    const texto = card.textContent ?? "";

    expect(texto).toContain("R$ 1.000,00");
    expect(texto).toContain("R$ 300,00");
    expect(texto).not.toContain("R$ 1.100,00");
    expect(texto).not.toContain("R$ 550,00");

    const linhaCancelada = blocoDe(within(card).getByText("Doce de leite")).parentElement as HTMLElement;
    expect(linhaCancelada.textContent).toContain("R$ 500,00");
    expect(within(linhaCancelada).getByText("cancelada")).toBeTruthy();

    const linhaOk = blocoDe(within(card).getByText("Queijo Canastra")).parentElement as HTMLElement;
    expect(within(linhaOk).queryByText("cancelada")).toBeNull();
  });

  it("Receita e ticket do painel não somam cancelada nem frete", async () => {
    mockFetch();
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    const receita = blocoDe(screen.getByText("Receita"));
    expect(receita.textContent).toContain("R$ 1.300,00");
    expect(receita.textContent).toContain("2 pedidos");
    const ticket = blocoDe(screen.getByText("Ticket médio"));
    expect(ticket.textContent).toContain("R$ 650,00");
  });
});
