/**
 * @vitest-environment jsdom
 *
 * Funil cumulativo (call de 01/10): o resumo mostra "Entraram já como cliente" — os clientes que
 * não passaram pelo closer — em vez de esconder o que o Arthur percebeu.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReportSummaryPanel, type CostComFrete, type FunnelComEntrada } from "./report-summary";
import type { ReportSummary } from "@/lib/traffic-summary";

const FUNNEL: FunnelComEntrada = {
  leads: 30, conversas: 26, closer: 10, clientes: 10,
  taxa_conversa: 0.8667, taxa_closer: 0.3846, taxa_cliente: 1, taxa_total: 0.3333,
  gargalo: "closer", entraram_ja_clientes: 6,
};
const summary = (funnel: FunnelComEntrada): ReportSummary => ({
  funnel,
  cost: { leads: 30, conversas: 26, closer: 10, clientes: 10, investimento: 0, receita: 0, roas: null,
          cpl: null, custo_conversa: null, custo_closer: null, cac: null },
  channels: [],
  timing_quality: { dias_ate_compra_mediana: null, amostra_dias: 0, pedidos_por_cliente: null,
                    recompra_pct: null, sem_rastreio_pct: null, nao_atribuido_pct: null },
});

afterEach(cleanup);

describe("ReportSummaryPanel — funil", () => {
  it("mostra quantos entraram já como cliente", () => {
    render(<ReportSummaryPanel summary={summary(FUNNEL)} mode="lead" />);
    expect(screen.getByText(/Entraram já como cliente/).textContent).toContain("6");
  });

  it("backend antigo (sem o campo) não mostra a linha", () => {
    const antigo: FunnelComEntrada = { ...FUNNEL };
    delete antigo.entraram_ja_clientes;
    render(<ReportSummaryPanel summary={summary(antigo)} mode="lead" />);
    expect(screen.queryByText(/Entraram já como cliente/)).toBeNull();
  });
});

describe("ReportSummaryPanel — receita sem frete e frete à parte (D7)", () => {
  const comCusto = (cost: Partial<CostComFrete>): ReportSummary => {
    const base = summary(FUNNEL);
    return { ...base, cost: { ...base.cost, ...cost } };
  };
  const statDe = (rotulo: string) => screen.getByText(rotulo).parentElement as HTMLElement;

  it("mostra a receita com a legenda 'sem frete' e o frete do período ao lado", () => {
    render(<ReportSummaryPanel summary={comCusto({ investimento: 1000, receita: 5000, frete: 320, roas: 5 })} mode="lead" />);
    const receita = statDe("Receita");
    expect(receita.textContent).toContain("R$ 5.000,00");
    expect(receita.textContent).toContain("sem frete");
    expect(statDe("Frete").textContent).toContain("R$ 320,00");
  });

  it("backend sem cost.frete mostra frete 0", () => {
    render(<ReportSummaryPanel summary={comCusto({ investimento: 1000, receita: 5000, roas: 5 })} mode="lead" />);
    expect(statDe("Frete").textContent).toContain("R$ 0,00");
  });

  it("sem investimento ainda mostra receita e frete", () => {
    render(<ReportSummaryPanel summary={comCusto({ investimento: 0, receita: 800, frete: 40 })} mode="lead" />);
    expect(screen.getByText(/Sem investimento sincronizado/)).toBeTruthy();
    expect(statDe("Receita").textContent).toContain("R$ 800,00");
    expect(statDe("Frete").textContent).toContain("R$ 40,00");
  });
});
