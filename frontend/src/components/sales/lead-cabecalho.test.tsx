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
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Sim" }));
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
});
