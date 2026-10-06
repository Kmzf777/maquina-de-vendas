/**
 * @vitest-environment jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const h = vi.hoisted(() => ({ maybeSingle: vi.fn() }));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle: h.maybeSingle }) }) }),
  }),
}));

import { LeadCabecalho } from "./lead-cabecalho";

const LEAD = {
  id: "lead-1",
  phone: "5531999998888",
  email: "compras@vidanatural.com",
  cnpj: "12345678000190",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  h.maybeSingle.mockReset();
  fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }) as Response);
  global.fetch = fetchMock as unknown as typeof fetch;
});
afterEach(cleanup);

function abrir(onSaveField = vi.fn()) {
  render(
    <LeadCabecalho lead={LEAD} currentUserEmail="joao@cafecanastra.com" onSaveField={onSaveField} />,
  );
  return { onSaveField };
}

describe("LeadCabecalho", () => {
  it("mostra telefone, e-mail e CNPJ formatado", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    abrir();
    expect(screen.getByText("5531999998888")).toBeTruthy();
    expect(screen.getByText("compras@vidanatural.com")).toBeTruthy();
    expect(screen.getByText("12.345.678/0001-90")).toBeTruthy();
  });

  it("copia o telefone", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    abrir();
    fireEvent.click(screen.getByRole("button", { name: "Copiar telefone" }));
    expect(writeText).toHaveBeenCalledWith("5531999998888");
  });

  it("selo 'auto' quando o sistema marcou", async () => {
    h.maybeSingle.mockResolvedValue({
      data: { id: "lead-1", ja_era_cliente: true, ja_era_cliente_fonte: "auto" },
      error: null,
    });
    abrir();
    expect(await screen.findByText("auto")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sim" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("o vendedor sobrescreve: Não grava fonte vendedor, por e em", async () => {
    h.maybeSingle.mockResolvedValue({
      data: { id: "lead-1", ja_era_cliente: true, ja_era_cliente_fonte: "auto" },
      error: null,
    });
    abrir();
    await screen.findByText("auto");
    fireEvent.click(screen.getByRole("button", { name: "Não" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/leads/lead-1");
    expect(init.method).toBe("PATCH");
    const corpo = JSON.parse(String(init.body));
    expect(corpo).toMatchObject({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
    });
    expect(typeof corpo.ja_era_cliente_em).toBe("string");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Não" }).getAttribute("aria-pressed")).toBe("true"),
    );
    expect(screen.queryByText("auto")).toBeNull();
  });

  it("falha ao gravar volta ao valor anterior e avisa", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ error: "boom" }) } as Response);
    abrir();
    fireEvent.click(await screen.findByRole("button", { name: "Sim" }));
    expect(await screen.findByText("boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sim" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("CNPJ digitado com máscara é gravado só com dígitos", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    const { onSaveField } = abrir();
    fireEvent.click(screen.getByText("12.345.678/0001-90"));
    const campo = screen.getByDisplayValue("12.345.678/0001-90");
    fireEvent.change(campo, { target: { value: "11.222.333/0001-81" } });
    fireEvent.keyDown(campo, { key: "Enter" });
    expect(onSaveField).toHaveBeenCalledWith("cnpj", "11222333000181");
  });

  it("banco sem a migração do P0 (coluna não existe): o toggle não aparece", async () => {
    h.maybeSingle
      .mockResolvedValueOnce({ data: null, error: { code: "42703", message: "column leads.ja_era_cliente does not exist" } })
      .mockResolvedValueOnce({ data: { id: "lead-1", name: "Iago" }, error: null });
    abrir();
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalledTimes(2));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("group", { name: "Já é cliente?" })).toBeNull();
    // O resto do cabeçalho continua.
    expect(screen.getByText("compras@vidanatural.com")).toBeTruthy();
  });

  it("PATCH em voo de um lead não vaza para o lead seguinte", async () => {
    h.maybeSingle.mockImplementation(async () => ({
      data: { id: "x", ja_era_cliente: null, ja_era_cliente_fonte: null },
      error: null,
    }));
    let responder: (r: Response) => void = () => {};
    fetchMock.mockImplementationOnce(() => new Promise<Response>((r) => { responder = r; }));
    const { rerender } = render(
      <LeadCabecalho lead={{ ...LEAD, id: "lead-voo-a" }} currentUserEmail="joao@cafecanastra.com" onSaveField={vi.fn()} />,
    );
    const sim = await screen.findByRole("button", { name: "Sim" });
    await waitFor(() => expect((sim as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(sim);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    rerender(
      <LeadCabecalho lead={{ ...LEAD, id: "lead-voo-b" }} currentUserEmail="joao@cafecanastra.com" onSaveField={vi.fn()} />,
    );
    const simB = await screen.findByRole("button", { name: "Sim" });
    // O lead B não herda o "salvando" nem a resposta otimista do A.
    await waitFor(() => expect((simB as HTMLButtonElement).disabled).toBe(false));
    expect(simB.getAttribute("aria-pressed")).toBe("false");

    responder({ ok: false, status: 500, json: async () => ({ error: "falhou o A" }) } as Response);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("falhou o A")).toBeNull();
    expect(screen.getByRole("button", { name: "Sim" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("CNPJ apagado grava null, não string vazia", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    const { onSaveField } = abrir();
    fireEvent.click(screen.getByText("12.345.678/0001-90"));
    const campo = screen.getByDisplayValue("12.345.678/0001-90");
    fireEvent.change(campo, { target: { value: "" } });
    fireEvent.keyDown(campo, { key: "Enter" });
    expect(onSaveField).toHaveBeenCalledWith("cnpj", null);
  });
});
