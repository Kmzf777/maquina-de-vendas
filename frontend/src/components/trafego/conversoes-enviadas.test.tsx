/**
 * @vitest-environment jsdom
 *
 * Aba "Conversões enviadas": erro da API aparece como erro (não como "nenhuma conversão"),
 * filtros ficam na tela durante o carregamento, resposta velha é descartada quando o filtro
 * muda rápido, e o card Lead mostra "—" na Meta (a Meta não recebe a etapa lead).
 * O Radix Select não roda no jsdom: o módulo é trocado por um equivalente simples.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children, ...p }: { children: ReactNode; "aria-label"?: string }) => (
    <button type="button" aria-label={p["aria-label"]}>{children}</button>
  ),
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));

import { ConversoesEnviadas } from "./conversoes-enviadas";

type Resposta = { ok: boolean; status: number; body: unknown };

function fetchControlado() {
  const pendentes: { url: string; signal?: AbortSignal; resolver: (r: Resposta) => void }[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => new Promise((resolve) => {
    pendentes.push({
      url, signal: init?.signal ?? undefined,
      resolver: (r) => resolve({ ok: r.ok, status: r.status, json: async () => r.body }),
    });
  })));
  return pendentes;
}

const vazio = { rows: [], counts: [], truncated: false };
const linha = (id: string, nome: string) => ({
  id, lead_id: `L-${id}`, platform: "google", stage: "purchase", status: "enviado",
  event_at: "2026-10-07T15:00:00Z", value: 100, currency: "BRL", segment: "atacado",
  campaign_name: null, click_id_type: "gclid", attempts: 1, last_error: null, sent_at: null,
  lead: { name: nome },
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const props = { period: "30d", dateFrom: "", dateTo: "", refreshTick: 0 };

describe("ConversoesEnviadas", () => {
  it("resposta de erro vira estado de erro, não 'Nenhuma conversão'", async () => {
    const p = fetchControlado();
    render(<ConversoesEnviadas {...props} />);
    await act(async () => p[0].resolver({ ok: false, status: 500, body: { error: "Backend indisponível" } }));
    expect(await screen.findByText(/Não foi possível carregar as conversões/)).toBeTruthy();
    expect(screen.queryByText(/Nenhuma conversão/)).toBeNull();
  });

  it("filtros continuam montados durante o carregamento", () => {
    fetchControlado();
    render(<ConversoesEnviadas {...props} />);
    expect(screen.getByLabelText("Etapa")).toBeTruthy();
    expect(screen.getByLabelText("Plataforma")).toBeTruthy();
    expect(screen.getByLabelText("Status")).toBeTruthy();
  });

  it("descarta a resposta velha quando o filtro muda antes de ela chegar", async () => {
    const p = fetchControlado();
    const { rerender } = render(<ConversoesEnviadas {...props} />);
    rerender(<ConversoesEnviadas {...props} period="7d" />);
    expect(p).toHaveLength(2);
    expect(p[0].signal?.aborted).toBe(true);
    await act(async () => p[1].resolver({ ok: true, status: 200, body: { ...vazio, rows: [linha("2", "Nova")] } }));
    await act(async () => p[0].resolver({ ok: true, status: 200, body: { ...vazio, rows: [linha("1", "Velha")] } }));
    await waitFor(() => expect(screen.getByText("Nova")).toBeTruthy());
    expect(screen.queryByText("Velha")).toBeNull();
  });

  it("card Lead mostra — na Meta (a Meta não recebe lead)", async () => {
    const p = fetchControlado();
    render(<ConversoesEnviadas {...props} />);
    await act(async () => p[0].resolver({
      ok: true, status: 200,
      body: { ...vazio, counts: [{ stage: "lead", platform: "google", status: "enviado", n: 3 }] },
    }));
    const card = (await screen.findByTestId("card-lead"));
    const meta = within(card).getByTestId("card-lead-meta");
    expect(meta.textContent).toContain("—");
    expect(within(card).getByTestId("card-lead-google").textContent).toContain("3");
  });
});
