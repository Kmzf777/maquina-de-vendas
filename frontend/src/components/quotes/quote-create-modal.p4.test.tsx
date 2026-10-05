/**
 * @vitest-environment jsdom
 *
 * P4 da call de 01/10 — o modal de orçamento aberto pela conversa (só
 * `leadId`, sem `pickLead`) precisa pré-preencher o cadastro do Bling com o lead.
 *
 * `BlingOrderForm` é trocado por um dublê que publica um pedido válido: o que
 * se testa aqui é o modal, não o catálogo (coberto em bling-order-form*.test).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const h = vi.hoisted(() => ({
  maybeSingle: vi.fn(),
  status: { enabled: true, accounts: [], loading: false, error: null as string | null },
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle: h.maybeSingle }) }) }),
  }),
}));

vi.mock("@/hooks/use-bling-status", () => ({ useBlingStatus: () => h.status }));

vi.mock("@/components/sales/bling-order-form", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    BlingOrderForm: ({
      onChange,
      meta,
    }: {
      onChange: (r: unknown) => void;
      meta: { leadId: string };
    }) => {
      React.useEffect(() => {
        onChange({
          valid: true,
          total: 60,
          installments: [{ valor: 60, dataVencimento: "2026-10-06" }],
          payload: {
            lead_id: meta.leadId,
            deal_id: null,
            sold_at: "2026-10-06",
            sold_by: null,
            notes: "",
            items: [
              {
                bling_product_id: 16536419853,
                codigo: null,
                descricao: "Kit Degustação",
                unidade: "UN",
                quantidade: 1,
                valor_unitario: 60,
                desconto_percentual: 0,
              },
            ],
            payment: { method_id: 1, terms: [0] },
          },
        });
      }, [onChange, meta.leadId]);
      return null;
    },
  };
});

import { QuoteCreateModal } from "./quote-create-modal";


const LEAD_VIDA = {
  id: "lead-1",
  name: "Iago",
  phone: "5531999998888",
  email: "compras@vidanatural.com",
  cnpj: "12345678000190",
  razao_social: "VIDA NATURAL LTDA",
  ja_era_cliente: true,
  ja_era_cliente_fonte: "auto",
};

type Chamada = { url: string; method: string; body: unknown };
let chamadas: Chamada[] = [];

function mockFetch() {
  chamadas = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    chamadas.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const json = (status: number, corpo: unknown) =>
      ({ ok: status < 300, status, headers: new Headers({ "content-type": "application/json" }), json: async () => corpo }) as Response;
    if (url.startsWith("/api/quotes") && method === "POST")
      return json(409, { error: "contact_unresolved", status: "missing", candidates: [] });
    return json(200, []);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  h.maybeSingle.mockReset();
  mockFetch();
});

afterEach(() => {
  cleanup();
});

describe("QuoteCreateModal — pré-preenchimento (P4.1)", () => {
  it("aberto pela conversa, o cadastro do Bling nasce com os dados do lead", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    render(
      <QuoteCreateModal
        leadId="lead-1"
        lockedDealId="deal-1"
        conversationId="conv-1"
        currentUserEmail="joao@cafecanastra.com"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    const enviar = await screen.findByRole("button", { name: "Gerar orçamento" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByDisplayValue("VIDA NATURAL LTDA")).toBeTruthy();
    expect(screen.getByDisplayValue("12345678000190")).toBeTruthy();
    expect(screen.getByDisplayValue("compras@vidanatural.com")).toBeTruthy();
    expect(chamadas.some((c) => c.url === "/api/leads")).toBe(false);
  });
});
