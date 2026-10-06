/**
 * @vitest-environment jsdom
 *
 * O `Popover` do Radix é trocado por um dublê que só mostra/esconde o
 * conteúdo: abrir o Popover de verdade no jsdom prende o worker num laço do
 * posicionamento (floating-ui sem layout) — mesmo motivo de
 * `bling-order-form.test.tsx` não abrir o Select. O que se testa aqui é a
 * lista de produtos, não o posicionamento.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/components/ui/popover", async () => {
  const { dublePopover } = await import("./popover-duble.test-utils");
  return dublePopover();
});

import { BlingOrderForm } from "./bling-order-form";

const META = { leadId: "lead-1", dealId: null, soldAt: "2026-10-06", soldBy: null, notes: "" };
const produto = (id: number, nome: string, preco = 10) => ({
  id, nome, codigo: null, preco, unidade: "UN", saldo_virtual: null, imagem_url: null,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockCatalogo() {
  const urls: string[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    urls.push(url);
    let data: unknown[] = [];
    if (url.includes("q=kit%20degust")) data = [produto(3, "KIT DEGUSTAÇÃO 1°", 80)];
    else if (url.startsWith("/api/bling/products"))
      data = [produto(1, "Café Clássico Moído 250g", 28.7), produto(2, "Kit Degustação", 60)];
    return { ok: true, json: async () => ({ data }) } as Response;
  }) as unknown as typeof fetch;
  return urls;
}

describe("BlingOrderForm — kits no topo (P4.5)", () => {
  it("abre o seletor com o grupo Kits antes dos demais produtos", async () => {
    const urls = mockCatalogo();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o produto/ }));
    expect(await screen.findByText("Kits")).toBeTruthy();
    await screen.findByText("Café Clássico Moído 250g");
    const nomes = screen
      .getAllByRole("button")
      .map((b) => b.textContent ?? "")
      .filter((t) => /KIT|Kit|Café/.test(t));
    const iKit1 = nomes.findIndex((t) => t.includes("KIT DEGUSTAÇÃO 1°"));
    const iKit = nomes.findIndex((t) => t.startsWith("Kit Degustação"));
    const iCafe = nomes.findIndex((t) => t.includes("Café Clássico"));
    expect(iKit1).toBeGreaterThanOrEqual(0);
    expect(iKit).toBeGreaterThanOrEqual(0);
    expect(iKit1).toBeLessThan(iCafe);
    expect(iKit).toBeLessThan(iCafe);
    expect(urls.some((u) => u.includes("q=kit%20degust"))).toBe(true);
  });

  it("escolher um kit que só veio pela busca de kits preenche a linha", async () => {
    mockCatalogo();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o produto/ }));
    const kit = await screen.findByText("KIT DEGUSTAÇÃO 1°");
    fireEvent.click(kit.closest("button")!);
    const linha = screen.getByRole("button", { name: /KIT DEGUSTAÇÃO 1°/ });
    expect(within(linha).getByText("KIT DEGUSTAÇÃO 1°")).toBeTruthy();
  });
});
