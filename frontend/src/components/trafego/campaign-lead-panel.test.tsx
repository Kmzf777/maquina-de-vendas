/**
 * @vitest-environment jsdom
 *
 * D7 (cartão 1e6381fe) no painel do lead em /trafego: cada venda do card "Vendas" aparece
 * sem frete; a cancelada continua na lista, com o valor sem frete e o selo "cancelada"; o
 * total (Receita) e o ticket não somam cancelada nem frete.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

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

function mockFetch(payload: LeadOverview = PAYLOAD) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url === "/api/leads/L1/overview" ? payload : { campanhas: [] };
    return { ok: true, status: 200, json: async () => body };
  }));
}

/** O <div> do card/stat que contém o rótulo. */
const blocoDe = (rotulo: HTMLElement) => rotulo.parentElement as HTMLElement;

afterEach(() => { cleanup(); vi.unstubAllGlobals(); push.mockClear(); });

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

// Cartão 70d844a6: lead sem conversa (ex.: importado do Bling) não pode levar a um
// /conversas calado. Com telefone utilizável o botão vira "Iniciar conversa" e leva ao
// aviso do /conversas, onde está o modal; sem telefone fica desabilitado com o motivo.
describe("CampaignLeadPanel — botão de conversa", () => {
  it("lead sem conversa e com telefone: 'Iniciar conversa' habilitado leva ao /conversas", async () => {
    mockFetch({ ...PAYLOAD, has_conversation: false });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    const botao = await screen.findByRole("button", { name: /Iniciar conversa/ });
    expect((botao as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /Abrir conversa/ })).toBeNull();
    fireEvent.click(botao);
    expect(push).toHaveBeenCalledWith("/conversas?lead_id=L1");
  });

  it("lead sem conversa e sem telefone utilizável: desabilitado com 'Sem telefone para WhatsApp'", async () => {
    mockFetch({ ...PAYLOAD, lead: { ...PAYLOAD.lead, phone: "bling-1" }, has_conversation: false });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    const botao = await screen.findByRole("button", { name: /Sem telefone para WhatsApp/ });
    expect((botao as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Iniciar conversa/ })).toBeNull();
    fireEvent.click(botao);
    expect(push).not.toHaveBeenCalled();
  });

  it("lead com conversa: 'Abrir conversa' habilitado", async () => {
    mockFetch({ ...PAYLOAD, has_conversation: true });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    const botao = screen.getByRole("button", { name: /Abrir conversa/ });
    expect((botao as HTMLButtonElement).disabled).toBe(false);
  });

  it("sem a informação (payload antigo ou erro): continua habilitado", async () => {
    mockFetch(PAYLOAD);
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    expect((screen.getByRole("button", { name: /Abrir conversa/ }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("CampaignLeadPanel — trilha com venda de antes da entrada", () => {
  it("mostra 'Já era cliente' com a contagem e a data da mais antiga", async () => {
    mockFetch({
      ...PAYLOAD,
      sales: [
        venda({ id: "a1", value: 100, sold_at: "2026-02-27T12:00:00Z" }),
        venda({ id: "a2", value: 100, sold_at: "2026-06-01T12:00:00Z" }),
      ],
    });
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    expect(await screen.findByText(/Já era cliente: 2 compras antes de entrar, desde 27\/02\/2026\./)).toBeTruthy();
    expect(screen.queryByText(/Ciclo fechado/)).toBeNull();
  });

  it("sem venda anterior, a linha não aparece", async () => {
    mockFetch();
    render(<CampaignLeadPanel target={TARGET} onClose={() => {}} />);
    await screen.findByText("Vendas");
    expect(screen.queryByText(/Já era cliente/)).toBeNull();
  });
});
