/**
 * @vitest-environment jsdom
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências): asserções com a API crua do
 * DOM/`screen`, mesmo padrão de lead-bling-section.test.tsx.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { LeadTimeline, type TimelineResponse } from "./lead-timeline";

const resposta = (corpo: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => corpo }) as Response;

function mockFetch(r: Response) {
  const fn = vi.fn(() => Promise.resolve(r));
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

const EXEMPLO: TimelineResponse = {
  partial: [],
  items: [
    {
      kind: "evento", id: "e4", event_type: "venda_cancelada", at: "2026-09-25T15:00:00Z", source: "crm",
      old_value: null, new_value: "30", metadata: { valor: 30, produto: "Clássico 250g" },
    },
    {
      kind: "evento", id: "e3", event_type: "venda", at: "2026-09-20T15:00:00Z", source: "bling",
      old_value: null, new_value: "60", metadata: { valor: 60, produto: "Kit Degustação", kit: true, origin: "bling" },
    },
    { kind: "conversou", id: "conversou:2026-09-18", dia: "2026-09-18", at: "2026-09-18T20:00:00Z", mensagens: 3 },
    {
      kind: "evento", id: "e2", event_type: "etapa", at: "2026-09-12T12:00:00Z", source: "crm",
      old_value: "Novo", new_value: "Qualificado",
      metadata: { pipeline_nome: "Atacado", de_label: "Novo", para_label: "Qualificado" },
    },
    {
      kind: "evento", id: "e1", event_type: "entrada", at: "2026-09-10T12:00:00Z", source: "ctwa",
      old_value: null, new_value: "Meta Ads", metadata: { canal: "Meta Ads", campanha_nome: "CTWA Atacado", meta_ad_id: "ad-1" },
    },
    {
      kind: "evento", id: "e0", event_type: "entrada", at: "2026-08-01T12:00:00Z", source: "ctwa",
      old_value: null, new_value: "Meta Ads", metadata: { canal: "Meta Ads", meta_ad_id: "ad-2" },
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LeadTimeline", () => {
  it("busca a rota do lead e desenha os itens na ordem recebida (mais novo primeiro)", async () => {
    const f = mockFetch(resposta(EXEMPLO));
    const { container } = render(<LeadTimeline leadId="lead-1" />);
    await screen.findAllByText("Entrada — Meta Ads");
    expect(f).toHaveBeenCalledWith("/api/leads/lead-1/timeline");
    const tipos = [...container.querySelectorAll("li")].map((li) => li.getAttribute("data-tipo"));
    expect(tipos).toEqual(["venda_cancelada", "venda", "conversou", "etapa", "entrada", "entrada"]);
  });

  it("entrada mostra canal e campanha; sem nome, 'Campanha não identificada'", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("CTWA Atacado")).toBeTruthy();
    expect(screen.getByText("Campanha não identificada")).toBeTruthy();
  });

  it("venda mostra valor, produto e os selos kit e Bling; cancelada aparece", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText(/R\$\s60,00 · Kit Degustação/)).toBeTruthy();
    expect(screen.getByText("kit")).toBeTruthy();
    expect(screen.getByText("Bling")).toBeTruthy();
    expect(screen.getByText("Venda cancelada")).toBeTruthy();
    expect(screen.getByText(/R\$\s30,00 · Clássico 250g/)).toBeTruthy();
  });

  it("marcador 'conversou' mostra o dia e quantas mensagens; etapa mostra funil e de → para", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Conversou")).toBeTruthy();
    expect(screen.getByText("3 mensagens do cliente")).toBeTruthy();
    expect(screen.getByText("18/09/2026")).toBeTruthy();
    expect(screen.getByText("Etapa — Atacado")).toBeTruthy();
    expect(screen.getByText("Novo → Qualificado")).toBeTruthy();
  });

  it("lista vazia", async () => {
    mockFetch(resposta({ items: [], partial: [] }));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Nenhum evento registrado ainda.")).toBeTruthy();
  });

  it("erro HTTP mostra mensagem de falha", async () => {
    mockFetch(resposta({ error: "boom" }, false, 500));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Não foi possível carregar a linha do tempo.")).toBeTruthy();
  });

  it("seção que falhou aparece como aviso, sem esconder o resto", async () => {
    mockFetch(resposta({ items: EXEMPLO.items.slice(2, 3), partial: ["eventos"] }));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText(/Parte da linha do tempo não carregou: eventos/)).toBeTruthy();
    expect(screen.getByText("Conversou")).toBeTruthy();
  });
});
