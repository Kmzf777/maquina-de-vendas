/**
 * @vitest-environment jsdom
 *
 * Recusa do Bling com `fields` (motivo campo a campo): o vendedor vê a lista
 * de motivos no lugar da frase genérica — no pedido (422) e no cadastro do
 * contato pelo resolvedor (400 do POST /contatos). Mesma armação do
 * `sale-create-modal.p4.test.tsx`.
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

import { SaleCreateModal } from "./sale-create-modal";

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

const GENERICA =
  "O contato não pode ser salvo pois ocorreram problemas com sua validação.";
const RECUSA_CONTATO = {
  error: "validation",
  message: "Não foi possível salvar o contato.",
  detail: GENERICA,
  type: "VALIDATION_ERROR",
  fields: [
    { campo: "CPF/CNPJ", mensagem: "número inválido" },
    { campo: "CEP", mensagem: "O CEP informado é inválido" },
  ],
};
let respostaPedido: () => Response;
const resposta = (status: number, corpo: unknown) =>
  ({ ok: status < 300, status, json: async () => corpo }) as Response;

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
    if (url === "/api/bling/orders" && method === "POST") return respostaPedido();
    if (url === "/api/bling/contacts" && method === "POST") return json(400, RECUSA_CONTATO);
    if (url.startsWith("/api/leads/") && method === "PATCH") return json(200, {});
    if (url === "/api/sales" && method === "POST") return json(201, {});
    return json(200, []);
  }) as unknown as typeof fetch;
}

function abrir(extra: Partial<React.ComponentProps<typeof SaleCreateModal>> = {}) {
  const onSaved = vi.fn();
  render(
    <SaleCreateModal
      leadId="lead-1"
      lockedDealId="deal-1"
      lockedDealTitle="Kit degustação"
      conversationId="conv-1"
      currentUserEmail="joao@cafecanastra.com"
      onClose={vi.fn()}
      onSaved={onSaved}
      {...extra}
    />,
  );
  return { onSaved };
}

beforeEach(() => {
  h.maybeSingle.mockReset();
  mockFetch();
});

afterEach(() => {
  cleanup();
});

describe("SaleCreateModal — recusa do Bling com fields", () => {
  it("422 do pedido mostra os motivos campo a campo, não a frase genérica", async () => {
    respostaPedido = () =>
      resposta(422, {
        error: "validation",
        message: "Não foi possível salvar o pedido.",
        detail: "O pedido não pode ser salvo pois ocorreram problemas com sua validação.",
        fields: [{ campo: "", mensagem: "A natureza de operação é obrigatória" }],
      });
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir();
    const enviar = await screen.findByRole("button", { name: "Lançar pedido no Bling" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByText(/A natureza de operação é obrigatória/)).toBeTruthy();
    expect(screen.queryByText(/problemas com sua validação/)).toBeNull();
  });

  it("422 sem fields continua mostrando message + detail", async () => {
    respostaPedido = () =>
      resposta(422, { error: "validation", message: "Pedido recusado.", detail: "Estoque." });
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir();
    const enviar = await screen.findByRole("button", { name: "Lançar pedido no Bling" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByText("Pedido recusado. Estoque.")).toBeTruthy();
  });

  it("cadastro do contato recusado mostra 'CPF/CNPJ: …' e 'CEP: …'", async () => {
    respostaPedido = () =>
      resposta(409, { status: "missing", reason: "sem_correspondencia", candidates: [] });
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir();
    const enviar = await screen.findByRole("button", { name: "Lançar pedido no Bling" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    const cadastrar = await screen.findByRole("button", { name: "Cadastrar e lançar o pedido" });
    // CNPJ com DV válido: o formulário não pode barrar antes do Bling.
    fireEvent.change(screen.getByDisplayValue("12345678000190"), {
      target: { value: "11222333000181" },
    });
    fireEvent.click(cadastrar);

    expect(await screen.findByText(/CPF\/CNPJ: número inválido/)).toBeTruthy();
    expect(screen.getByText(/CEP: O CEP informado é inválido/)).toBeTruthy();
    expect(screen.queryByText(/problemas com sua validação/)).toBeNull();
  });
});
