/**
 * @vitest-environment jsdom
 *
 * Visão do período (/trafego, 12/11/2026): leads e closer de quem entrou, pedidos e receita de
 * toda venda do período, na mesma linha. Números de 05–11/11/2026 conferidos em produção.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { CampaignReportTable, type CampaignRow } from "./campaign-report-table";
import { ReportSummaryPanel } from "./report-summary";
import { collapsedLine, type ReportSummary } from "@/lib/traffic-summary";

afterEach(cleanup);

const linha = (o: Partial<CampaignRow>): CampaignRow => ({
  channel: "Meta Ads", campaign: "X", leads: 0, conversas: 0, closer: 0, clientes: 0, pedidos: 0,
  receita: 0, frete: 0, investimento: 0, roas: null, ticket_medio: 0, conversao: 0, ...o,
});

const rows: CampaignRow[] = [
  linha({ channel: "Bling", campaign: "(sem campanha)", clientes: 37, pedidos: 37, receita: 10572.83, ticket_medio: 285.75, conversao: null }),
  linha({ channel: "Google Ads", campaign: "Leads-Search | Atacado", leads: 13, conversas: 11, closer: 6, clientes: 1, pedidos: 1, receita: 79.4, investimento: 154.25, roas: 0.51, ticket_medio: 79.4, conversao: 0.0769 }),
  linha({ channel: "Meta Ads", campaign: "Atacado | WA | 15.10.26", leads: 64, conversas: 64, closer: 22, investimento: 139.08, roas: 0, conversao: 0 }),
];

const total = { leads: 172, conversas: 166, closer: 60, clientes: 53, pedidos: 53, receita: 29410.93, investimento: 741.23, roas: 0.27, conversao: 0.3081 };

describe("visão do período", () => {
  it("mostra leads, closer, pedidos e investimento na mesma linha e explica a taxa", () => {
    render(<CampaignReportTable rows={rows} total={total} subtotals={{}} onRowClick={() => {}} periodo />);
    const meta = screen.getByText("Atacado | WA | 15.10.26").closest("tr")!;
    expect(within(meta).getAllByText("64").length).toBe(2); // leads e conversas
    expect(within(meta).getByText("22")).toBeTruthy();
    expect(within(meta).getByText("R$ 139,08")).toBeTruthy();
    // Bling: sem lead no período → "—", nunca 0% nem infinito
    const bling = screen.getByText("Bling").closest("tr")!;
    expect(within(bling).getAllByText("37").length).toBe(2); // clientes e pedidos
    expect(bling.textContent).toContain("—");
    expect(screen.getByText("Pedidos/lead")).toBeTruthy();
    expect(screen.getByTestId("nota-periodo").textContent).toContain("não da turma");
    expect(screen.getByText("30.8%")).toBeTruthy(); // total: 53 pedidos ÷ 172 leads
  });

  it("linha do funil com as duas pontas reais", () => {
    const summary = {
      funnel: { leads: 172, conversas: 166, closer: 60, clientes: 53, pedidos: 53, receita: 29410.93,
        taxa_conversa: null, taxa_closer: null, taxa_cliente: null, taxa_total: null, gargalo: null },
      cost: { leads: 0, conversas: 0, closer: 0, clientes: 0, investimento: 0, receita: 0, roas: null,
        cpl: null, custo_conversa: null, custo_closer: null, cac: null },
      channels: [],
      timing_quality: { dias_ate_compra_mediana: null, amostra_dias: 0, pedidos_por_cliente: null,
        recompra_pct: null, sem_rastreio_pct: null, nao_atribuido_pct: null },
    } as ReportSummary;
    expect(collapsedLine(summary, "periodo")).toBe("172 leads → 60 closer → 53 pedidos · R$ 29.410,93");
    render(<ReportSummaryPanel summary={summary} mode="periodo" />);
    expect(screen.getByTestId("nota-funil-periodo").textContent).toContain("toda venda do período");
  });
});
