/**
 * @vitest-environment jsdom
 *
 * Revisão do P4: o painel de venda/orçamento é não-modal, então o vendedor
 * pode trocar de conversa com ele aberto. Se o painel sobrevivesse à troca, o
 * modal (que guarda o lead no estado de abertura) gravaria a venda com o lead
 * de uma conversa e o `conversation_id` da outra — inclusive pedido no Bling.
 *
 * Os modais são dublês que registram cada render: o que se testa aqui é que o
 * `ContactDetail` nunca os renderiza para a conversa nova.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const h = vi.hoisted(() => ({
  renders: [] as { painel: string; leadId?: string; conversationId?: string | null }[],
}));

vi.mock("@/hooks/use-lead-sales", () => ({
  useLeadSales: () => ({
    sales: [],
    refetch: vi.fn(),
  }),
}));
vi.mock("@/hooks/use-lead-quotes", () => ({
  useLeadQuotes: () => ({ quotes: [], refetch: vi.fn() }),
}));
vi.mock("@/hooks/use-current-user", () => ({
  useCurrentUserEmail: () => "joao@cafecanastra.com",
}));
vi.mock("@/components/sales/lead-cabecalho", () => ({ LeadCabecalho: () => null }));
vi.mock("@/components/leads/lead-timeline", () => ({ LeadTimeline: () => null }));
vi.mock("@/components/deals/deal-create-modal", () => ({ DealCreateModal: () => null }));
vi.mock("./tabs/crm-notas-tab", () => ({ CrmNotasTab: () => null }));
vi.mock("./tabs/crm-campanhas-tab", () => ({ CrmCampanhasTab: () => null }));
vi.mock("./tabs/crm-metricas-tab", () => ({ CrmMetricasTab: () => null }));
vi.mock("./tabs/crm-perfil-tab", () => ({
  CrmPerfilTab: (p: {
    onCreateSale: () => void;
    onCreateQuote: () => void;
    onEditSale: (s: unknown) => void;
  }) => (
    <div>
      <button type="button" onClick={p.onCreateSale}>abrir venda</button>
      <button type="button" onClick={p.onCreateQuote}>abrir orçamento</button>
      <button
        type="button"
        onClick={() => p.onEditSale({ id: "venda-1", lead_id: "lead-a" })}
      >
        editar venda
      </button>
    </div>
  ),
}));
vi.mock("@/components/sales/sale-create-modal", () => ({
  SaleCreateModal: (p: { leadId?: string; conversationId?: string | null }) => {
    h.renders.push({ painel: "venda", leadId: p.leadId, conversationId: p.conversationId });
    return <div data-testid="painel-venda" />;
  },
}));
vi.mock("@/components/quotes/quote-create-modal", () => ({
  QuoteCreateModal: (p: { leadId?: string; conversationId?: string | null }) => {
    h.renders.push({ painel: "orcamento", leadId: p.leadId, conversationId: p.conversationId });
    return <div data-testid="painel-orcamento" />;
  },
}));

import { ContactDetail } from "./contact-detail";
import type { Conversation } from "@/lib/types";

const conversa = (id: string, leadId: string, nome: string) =>
  ({
    id,
    leads: { id: leadId, name: nome, phone: "5531999990000" },
    channels: null,
  }) as unknown as Conversation;

const A = conversa("conv-a", "lead-a", "Vida Natural");
const B = conversa("conv-b", "lead-b", "Empório Iago");

function montar(c: Conversation) {
  return (
    <ContactDetail conversation={c} tags={[]} leadTags={[]} onTagToggle={vi.fn()} />
  );
}

beforeEach(() => {
  h.renders = [];
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }) as Response) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("ContactDetail — trocar de conversa com o painel aberto", () => {
  it.each([
    ["abrir venda", "painel-venda"],
    ["abrir orçamento", "painel-orcamento"],
    ["editar venda", "painel-venda"],
  ])("'%s' aberto em A fecha ao trocar para B, sem nunca renderizar para B", (botao, testId) => {
    const { rerender } = render(montar(A));
    fireEvent.click(screen.getByRole("button", { name: botao }));
    expect(screen.getByTestId(testId)).toBeTruthy();

    rerender(montar(B));

    expect(screen.queryByTestId(testId)).toBeNull();
    // Nenhum render do painel com a conversa B: nem um quadro sequer em que o
    // modal (com o lead A no estado) visse o conversation_id de B.
    expect(h.renders.some((r) => r.conversationId === "conv-b")).toBe(false);

    // Voltar para A também não reabre o painel antigo.
    rerender(montar(A));
    expect(screen.queryByTestId(testId)).toBeNull();
  });
});
