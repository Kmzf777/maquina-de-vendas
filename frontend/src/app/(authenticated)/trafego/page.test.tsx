/**
 * @vitest-environment jsdom
 *
 * /trafego: as abas são botões de alternância acessíveis (type="button" + aria-pressed) e a aba
 * "Conversões enviadas" não busca o relatório de campanhas (que é pesado) à toa.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks/use-current-role", () => ({ useCurrentRole: () => ({ role: "admin", loading: false }) }));
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));
vi.mock("@/components/ui/switch", () => ({
  Switch: ({ checked, "aria-label": label }: { checked: boolean; "aria-label"?: string }) => (
    <input type="checkbox" role="switch" aria-label={label} checked={checked} readOnly />
  ),
}));
vi.mock("@/components/trafego/campaign-report-table", () => ({ CampaignReportTable: () => null }));
vi.mock("@/components/trafego/report-summary", () => ({ ReportSummaryPanel: () => null }));
vi.mock("@/components/trafego/conversoes-enviadas", () => ({
  ConversoesEnviadas: () => <div>aba-conversoes</div>,
}));

import TrafegoPage from "./page";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("TrafegoPage", () => {
  it("abas acessíveis e sem buscar o relatório na aba de conversões", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => ({ rows: [], total: {}, channel_subtotals: {} }) };
    }));
    render(<TrafegoPage />);
    const campanhas = screen.getByRole("button", { name: "Campanhas" });
    const conversoes = screen.getByRole("button", { name: "Conversões enviadas" });
    expect(campanhas.getAttribute("type")).toBe("button");
    expect(conversoes.getAttribute("type")).toBe("button");
    expect(campanhas.getAttribute("aria-pressed")).toBe("true");
    expect(conversoes.getAttribute("aria-pressed")).toBe("false");
    const antes = urls.filter((u) => u.startsWith("/api/traffic/report")).length;
    expect(antes).toBe(1);

    fireEvent.click(conversoes);
    expect(conversoes.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("aba-conversoes")).toBeTruthy();
    // Atualizar na aba de conversões não dispara o relatório de campanhas
    fireEvent.click(screen.getByRole("button", { name: /Atualizar/ }));
    await vi.waitFor(() => expect(urls).toContain("/api/traffic/sync"));
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(urls.filter((u) => u.startsWith("/api/traffic/report")).length).toBe(antes);

    fireEvent.click(campanhas);
    await vi.waitFor(() => expect(urls.filter((u) => u.startsWith("/api/traffic/report")).length).toBe(antes + 1));
  });
});


describe("TrafegoPage — frente F1", () => {
  it("abre por venda, mostra a frase e pede o relatório com mode=sale", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => ({ rows: [], total: {}, channel_subtotals: {} }) };
    }));
    render(<TrafegoPage />);
    const sw = screen.getByRole("switch", { name: "Por venda" }) as HTMLInputElement;
    expect(sw.checked).toBe(true);
    expect(screen.getByTestId("frase-modo").textContent).toBe("Por venda: toda venda do período, de lead novo ou antigo");
    await vi.waitFor(() => expect(urls.some((u) => u.startsWith("/api/traffic/report") && u.includes("mode=sale"))).toBe(true));
  });

  it("mostra embaixo do Atualizar quando cada plataforma sincronizou ou falhou", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url === "/api/traffic/sync-status"
        ? { plataformas: {
            google: { status: "falha", motivo: "HTTP 404 em v22", em: "2026-11-06T17:30:00Z" },
            meta: { status: "ok", linhas: 12, em: "2026-11-06T17:31:00Z" },
          } }
        : { rows: [], total: {}, channel_subtotals: {} },
    })));
    render(<TrafegoPage />);
    const status = await screen.findByTestId("status-sync");
    expect(status.textContent).toContain("Google: falhou em 06/11 14:30: HTTP 404 em v22");
    expect(status.textContent).toContain("Meta: sincronizado em 06/11 14:31");
  });
});
