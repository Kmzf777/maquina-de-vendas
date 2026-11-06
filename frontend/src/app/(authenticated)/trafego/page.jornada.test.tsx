/**
 * @vitest-environment jsdom
 *
 * /trafego (F5): o seletor "Atribuir por" troca as linhas sem nova consulta, o bloco de jornadas
 * e o "Sem rastreio" aparecem, e a linha clicada na primeira origem leva a atribuição junto.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/use-current-role", () => ({ useCurrentRole: () => ({ role: "admin", loading: false }) }));
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}));
vi.mock("@/components/ui/switch", () => ({ Switch: () => null }));
vi.mock("@/components/trafego/report-summary", () => ({ ReportSummaryPanel: () => null }));
vi.mock("@/components/trafego/conversoes-enviadas", () => ({ ConversoesEnviadas: () => null }));
vi.mock("@/components/trafego/campaign-report-table", () => ({
  CampaignReportTable: ({ rows, onRowClick }: { rows: { channel: string; campaign: string }[]; onRowClick: (r: unknown) => void }) => (
    <ul>
      {rows.map((r) => (
        <li key={r.channel + r.campaign}>
          <button type="button" onClick={() => onRowClick(r)}>{`linha ${r.channel} · ${r.campaign}`}</button>
        </li>
      ))}
    </ul>
  ),
}));

import TrafegoPage from "./page";

const linha = (channel: string, campaign: string) => ({ channel, campaign, leads: 1 });
const ULTIMA = { rows: [linha("Google Ads", "Search | Marca"), linha("Sem rastreio", "(sem campanha)")], total: { leads: 2 }, channel_subtotals: {} };
const PRIMEIRA = { rows: [linha("Meta Ads", "Meta | Atacado"), linha("Sem rastreio", "(sem campanha)")], total: { leads: 2 }, channel_subtotals: {} };
const REPORT = {
  mode: "sale", period: "30d", ...ULTIMA, atribuicao: "ultima",
  por_atribuicao: { ultima: ULTIMA, primeira: PRIMEIRA },
  jornadas: { leads: 1, clientes: 1, pedidos: 1, receita: 500, total_leads: 2,
    caminhos: [{ caminho: "Meta Ads → Google Ads", leads: 1, clientes: 1, pedidos: 1, receita: 500 }] },
  sem_rastreio: { leads: 1, motivos: [{ motivo: "Nunca mandou mensagem", leads: 1 }] },
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); push.mockReset(); });

describe("TrafegoPage — jornada", () => {
  it("troca a atribuição sem buscar de novo e mostra jornadas e sem rastreio", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => (url.startsWith("/api/traffic/report") ? REPORT : {}) };
    }));
    render(<TrafegoPage />);
    await screen.findByText("linha Google Ads · Search | Marca");
    expect(screen.getByRole("button", { name: "Última origem" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Meta Ads → Google Ads")).toBeTruthy();
    expect(screen.getByText("Sem rastreio: 1 lead")).toBeTruthy();
    const consultas = urls.filter((u) => u.startsWith("/api/traffic/report")).length;

    fireEvent.click(screen.getByRole("button", { name: "Primeira origem" }));
    expect(screen.getByText("linha Meta Ads · Meta | Atacado")).toBeTruthy();
    expect(screen.queryByText("linha Google Ads · Search | Marca")).toBeNull();
    expect(urls.filter((u) => u.startsWith("/api/traffic/report")).length).toBe(consultas);

    fireEvent.click(screen.getByText("linha Meta Ads · Meta | Atacado"));
    const destino = new URL(push.mock.calls[0][0], "http://x");
    expect(destino.pathname).toBe("/trafego/campanha");
    expect(destino.searchParams.get("atribuicao")).toBe("primeira");
    expect(destino.searchParams.get("channel")).toBe("Meta Ads");

    fireEvent.click(screen.getByRole("button", { name: "Ver leads" }));
    expect(new URL(push.mock.calls[1][0], "http://x").searchParams.get("channel")).toBe("Sem rastreio");
  });

  it("na última origem o link do detalhe não leva atribuição (rota de sempre)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true, status: 200, json: async () => (url.startsWith("/api/traffic/report") ? REPORT : {}),
    })));
    render(<TrafegoPage />);
    fireEvent.click(await screen.findByText("linha Google Ads · Search | Marca"));
    expect(new URL(push.mock.calls[0][0], "http://x").searchParams.get("atribuicao")).toBeNull();
  });
});
