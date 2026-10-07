/**
 * @vitest-environment jsdom
 *
 * Print do vendedor (07/10, tela de 1600 px): o painel de orçamento/venda
 * ficava POR CIMA do chat e cortava a mensagem em que o cliente mandou CPF,
 * nome, endereço e e-mail. Em /conversas (telas largas) o painel vira coluna
 * do layout: o `ContactDetail` dá lugar a ele e avisa a página, que recolhe a
 * lista de conversas.
 *
 * Os modais são dublês que montam o `PainelLateral` REAL: o que se testa é o
 * contexto chegando nele e o detalhe do contato cedendo a coluna.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/hooks/use-lead-sales", () => ({
  useLeadSales: () => ({ sales: [], refetch: vi.fn() }),
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
  CrmPerfilTab: (p: { onCreateSale: () => void; onCreateQuote: () => void }) => (
    <div>
      <button type="button" onClick={p.onCreateSale}>abrir venda</button>
      <button type="button" onClick={p.onCreateQuote}>abrir orçamento</button>
    </div>
  ),
}));
vi.mock("@/components/sales/sale-create-modal", async () => {
  const { PainelLateral } = await import("@/components/sales/painel-lateral");
  return {
    SaleCreateModal: (p: { onClose: () => void }) => (
      <PainelLateral titulo="Registrar venda — Vida Natural" onFechar={p.onClose}>
        <p>formulário de venda</p>
      </PainelLateral>
    ),
  };
});
vi.mock("@/components/quotes/quote-create-modal", async () => {
  const { PainelLateral } = await import("@/components/sales/painel-lateral");
  return {
    QuoteCreateModal: (p: { onClose: () => void }) => (
      <PainelLateral titulo="Novo orçamento — Vida Natural" onFechar={p.onClose}>
        <p>formulário de orçamento</p>
      </PainelLateral>
    ),
  };
});

import { ContactDetail } from "./contact-detail";
import type { Conversation } from "@/lib/types";

const conversa = (id: string) =>
  ({
    id,
    leads: { id: `lead-${id}`, name: "Vida Natural", phone: "5531999990000" },
    channels: null,
  }) as unknown as Conversation;

const espera = () => new Promise((r) => setTimeout(r, 20));

beforeEach(() => {
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }) as Response) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("ContactDetail — painel acoplado ao lado do chat (/conversas)", () => {
  it.each([
    ["abrir orçamento", "formulário de orçamento"],
    ["abrir venda", "formulário de venda"],
  ])("'%s': painel inline no layout, detalhe do contato escondido e página avisada", (botao, corpo) => {
    const avisos: boolean[] = [];
    const { container } = render(
      <ContactDetail
        conversation={conversa("a")}
        tags={[]}
        leadTags={[]}
        onTagToggle={vi.fn()}
        painelAcoplado
        onPainelAcopladoChange={(v) => avisos.push(v)}
      />,
    );
    const detalhe = screen.getByText("Perfil").closest("[data-slot='detalhe-contato']") as HTMLElement;
    expect(detalhe.className).not.toContain("hidden");
    expect(avisos.at(-1) ?? false).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: botao }));

    // Inline: dentro da árvore renderizada, não num portal no body.
    expect(container.contains(screen.getByText(corpo))).toBe(true);
    expect(container.querySelector('[data-slot="painel-acoplado"]')).toBeTruthy();
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeNull();
    // O detalhe cede a coluna (continua montado: aba e estado preservados).
    expect(detalhe.className).toContain("hidden");
    expect(avisos.at(-1)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));

    expect(screen.queryByText(corpo)).toBeNull();
    expect(detalhe.className).not.toContain("hidden");
    expect(avisos.at(-1)).toBe(false);
  });

  it("trocar de conversa fecha o painel acoplado e devolve a lista", () => {
    const avisos: boolean[] = [];
    const props = {
      tags: [],
      leadTags: [],
      onTagToggle: vi.fn(),
      painelAcoplado: true,
      onPainelAcopladoChange: (v: boolean) => avisos.push(v),
    };
    const { rerender } = render(<ContactDetail conversation={conversa("a")} {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "abrir orçamento" }));
    expect(avisos.at(-1)).toBe(true);

    rerender(<ContactDetail conversation={conversa("b")} {...props} />);

    expect(screen.queryByText("formulário de orçamento")).toBeNull();
    expect(avisos.at(-1)).toBe(false);
  });

  it("desmontar com o painel aberto avisa a página para devolver a lista", () => {
    const avisos: boolean[] = [];
    const { unmount } = render(
      <ContactDetail
        conversation={conversa("a")}
        tags={[]}
        leadTags={[]}
        onTagToggle={vi.fn()}
        painelAcoplado
        onPainelAcopladoChange={(v) => avisos.push(v)}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "abrir venda" }));
    unmount();
    expect(avisos.at(-1)).toBe(false);
  });

  it("sem `painelAcoplado` (tela estreita/celular) o painel continua sobreposto, no portal", async () => {
    const avisos: boolean[] = [];
    const { container } = render(
      <ContactDetail
        conversation={conversa("a")}
        tags={[]}
        leadTags={[]}
        onTagToggle={vi.fn()}
        onPainelAcopladoChange={(v) => avisos.push(v)}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "abrir orçamento" }));
    await espera();
    expect(screen.getByText("formulário de orçamento")).toBeTruthy();
    expect(container.contains(screen.getByText("formulário de orçamento"))).toBe(false);
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeTruthy();
    expect(avisos.includes(true)).toBe(false);
  });

  it("o modo fica fixo enquanto o painel está aberto (redimensionar não remonta o formulário)", () => {
    const props = { tags: [], leadTags: [], onTagToggle: vi.fn() };
    const { rerender, container } = render(
      <ContactDetail conversation={conversa("a")} {...props} painelAcoplado />,
    );
    fireEvent.click(screen.getByRole("button", { name: "abrir orçamento" }));
    const painel = container.querySelector('[data-slot="painel-acoplado"]');
    expect(painel).toBeTruthy();

    // A janela estreitou: o painel aberto segue o mesmo nó (não vira Sheet).
    rerender(<ContactDetail conversation={conversa("a")} {...props} painelAcoplado={false} />);

    expect(container.querySelector('[data-slot="painel-acoplado"]')).toBe(painel);
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeNull();
  });
});
