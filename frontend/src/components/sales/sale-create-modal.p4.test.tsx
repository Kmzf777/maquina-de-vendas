/**
 * @vitest-environment jsdom
 *
 * P4 da call de 01/10 — o modal de venda aberto pela conversa (só `leadId`,
 * sem `pickLead`) precisa: pré-preencher o cadastro do Bling com o lead e
 * exigir "Já é cliente?" quando o banco não sabe.
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
    if (url === "/api/bling/orders" && method === "POST")
      return json(409, { status: "missing", reason: "sem_correspondencia", candidates: [] });
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

describe("SaleCreateModal — pré-preenchimento (P4.1)", () => {
  it("aberto pela conversa, o cadastro do Bling nasce com os dados do lead", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir();
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    const enviar = await screen.findByRole("button", { name: "Lançar pedido no Bling" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByDisplayValue("VIDA NATURAL LTDA")).toBeTruthy();
    expect(screen.getByDisplayValue("12345678000190")).toBeTruthy();
    expect(screen.getByDisplayValue("compras@vidanatural.com")).toBeTruthy();
    expect(screen.getByDisplayValue("5531999998888")).toBeTruthy();
    // Nada de lista inteira de leads quando o modal vem da conversa.
    expect(chamadas.some((c) => c.url === "/api/leads")).toBe(false);
  });
});

describe("SaleCreateModal — 'Já é cliente?' obrigatório (P4.4)", () => {
  it("lead com ja_era_cliente nulo: pergunta e só libera Salvar com resposta", async () => {
    h.maybeSingle.mockResolvedValue({ data: { ...LEAD_VIDA, ja_era_cliente: null, ja_era_cliente_fonte: null }, error: null });
    const { onSaved } = abrir({ blingEnabled: false });
    expect(await screen.findByRole("group", { name: "Já é cliente?" })).toBeTruthy();
    const salvar = screen.getByRole("button", { name: "Registrar Venda" }) as HTMLButtonElement;
    expect(salvar.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Não" }));
    expect(salvar.disabled).toBe(false);

    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit degustação" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(salvar);

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const patch = chamadas.findIndex((c) => c.url === "/api/leads/lead-1" && c.method === "PATCH");
    const venda = chamadas.findIndex((c) => c.url === "/api/sales" && c.method === "POST");
    expect(patch).toBeGreaterThanOrEqual(0);
    expect(patch).toBeLessThan(venda);
    expect(chamadas[patch].body).toMatchObject({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
    });
  });

  it("lead que o sistema já sabe: não pergunta nem grava", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    const { onSaved } = abrir({ blingEnabled: false });
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Já é cliente?" })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar Venda" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(chamadas.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("banco sem a coluna (P0 não aplicado): não trava a venda", async () => {
    h.maybeSingle
      .mockResolvedValueOnce({ data: null, error: { code: "42703", message: "column does not exist" } })
      .mockResolvedValueOnce({ data: { id: "lead-1", name: "Iago" }, error: null });
    abrir({ blingEnabled: false });
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("group", { name: "Já é cliente?" })).toBeNull();
  });

  it("falha ao gravar a resposta: não registra a venda e mostra o erro", async () => {
    h.maybeSingle.mockResolvedValue({ data: { ...LEAD_VIDA, ja_era_cliente: null }, error: null });
    const original = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return { ok: false, status: 500, json: async () => ({ error: "falhou o PATCH" }) } as Response;
      return original(input, init);
    }) as unknown as typeof fetch;
    abrir({ blingEnabled: false });
    await screen.findByRole("group", { name: "Já é cliente?" });
    fireEvent.click(screen.getByRole("button", { name: "Sim" }));
    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar Venda" }));
    expect(await screen.findByText("falhou o PATCH")).toBeTruthy();
    expect(chamadas.some((c) => c.url === "/api/sales")).toBe(false);
  });
});

describe("SaleCreateModal — seletor de lead (P4.6)", () => {
  it("modo pickLead não carrega a lista inteira de leads", async () => {
    h.maybeSingle.mockResolvedValue({ data: null, error: null });
    render(
      <SaleCreateModal
        pickLead
        blingEnabled={false}
        currentUserEmail="joao@cafecanastra.com"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    expect(await screen.findByRole("button", { name: /Selecione o lead/ })).toBeTruthy();
    await waitFor(() => expect(chamadas.some((c) => c.url === "/api/users")).toBe(true));
    expect(chamadas.some((c) => c.url === "/api/leads")).toBe(false);
  });
});

describe("SaleCreateModal — lead e conversa congelados na abertura (revisão P4)", () => {
  it("prop de conversa/lead mudando com o painel aberto não mistura a venda", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    const props = {
      lockedDealId: "deal-1",
      lockedDealTitle: "Kit degustação",
      currentUserEmail: "joao@cafecanastra.com",
      blingEnabled: false,
      onClose: vi.fn(),
      onSaved: vi.fn(),
    };
    const { rerender } = render(
      <SaleCreateModal leadId="lead-1" conversationId="conv-1" {...props} />,
    );
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    rerender(<SaleCreateModal leadId="lead-2" conversationId="conv-2" {...props} />);

    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar Venda" }));

    await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
    const venda = chamadas.find((c) => c.url === "/api/sales" && c.method === "POST");
    expect(venda?.body).toMatchObject({ lead_id: "lead-1", conversation_id: "conv-1" });
  });

  it("o título diz para quem é a venda", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir({ blingEnabled: false });
    expect(await screen.findByText("Registrar venda — Iago")).toBeTruthy();
  });
});

describe("SaleCreateModal — Salvar espera o lead (revisão P4)", () => {
  it("bloqueia Salvar enquanto o lead carrega: a pergunta pode ainda aparecer", async () => {
    let entregar: (v: unknown) => void = () => {};
    h.maybeSingle.mockReturnValue(new Promise((r) => { entregar = r; }));
    abrir({ blingEnabled: false });
    const salvar = (await screen.findByRole("button", { name: "Registrar Venda" })) as HTMLButtonElement;
    expect(salvar.disabled).toBe(true);
    entregar({ data: LEAD_VIDA, error: null });
    await waitFor(() => expect(salvar.disabled).toBe(false));
  });

  it("erro ao carregar o lead bloqueia Salvar e avisa", async () => {
    h.maybeSingle.mockResolvedValue({ data: null, error: { code: "57014", message: "statement timeout" } });
    abrir({ blingEnabled: false });
    expect(await screen.findByText(/Não foi possível carregar o lead/)).toBeTruthy();
    const salvar = screen.getByRole("button", { name: "Registrar Venda" }) as HTMLButtonElement;
    expect(salvar.disabled).toBe(true);
  });
});
