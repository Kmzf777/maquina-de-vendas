/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SearchResults } from "./search-results";
import type { SaleSearchResult } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ children, href, className }: { children: React.ReactNode; href: string; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

afterEach(cleanup);

const venda = (p: Partial<SaleSearchResult> = {}): SaleSearchResult => ({
  id: "s1",
  product: "Microlote 1kg",
  value: 500,
  sold_at: "2026-10-20T15:00:00.000Z",
  notes: null,
  lead_id: "l1",
  lead_name: "Padaria",
  lead_phone: "5534999999999",
  deal_id: null,
  deal_title: null,
  total_count: 1,
  ...p,
});

function renderVendas(vendas: SaleSearchResult[]) {
  const vazio = { data: [], count: 0 };
  return render(
    <SearchResults
      tab="sales"
      onTabChange={() => {}}
      results={{ leads: vazio, deals: vazio, sales: { data: vendas, count: vendas.length }, conversations: vazio }}
    />,
  );
}

describe("SearchResults: venda (D7)", () => {
  it("mostra o valor sem frete", () => {
    renderVendas([venda({ value: 500, freight: 50, status: "registrada" })]);
    expect(document.body.textContent).toContain("450,00");
    expect(screen.queryByText(/cancelada/i)).toBeNull();
  });

  it("marca a venda cancelada", () => {
    renderVendas([venda({ value: 300, status: "cancelada" })]);
    expect(screen.getByText(/cancelada/i)).toBeTruthy();
    expect(document.body.textContent).toContain("300,00");
  });

  it("funcao SQL antiga (sem status/frete) mantem o comportamento atual", () => {
    renderVendas([venda({ value: 500 })]);
    expect(document.body.textContent).toContain("500,00");
    expect(screen.queryByText(/cancelada/i)).toBeNull();
  });
});
