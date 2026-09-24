import { describe, expect, it } from "vitest";
import { collapsedLine, fmtBRLOrDash, fmtDays, fmtPctOrDash, fmtRoasOrDash, type ReportSummary } from "./traffic-summary";

const base: ReportSummary = {
  funnel: { leads: 1240, conversas: 612, closer: 188, clientes: 41, taxa_conversa: 0.4935, taxa_closer: 0.3072, taxa_cliente: 0.2181, taxa_total: 0.0331, gargalo: "cliente" },
  cost: { investimento: 0, receita: 0, roas: null, leads: 0, conversas: 0, closer: 0, clientes: 0, cpl: null, custo_conversa: null, custo_closer: null, cac: null },
  channels: [],
  timing_quality: { dias_ate_compra_mediana: null, amostra_dias: 0, pedidos_por_cliente: null, recompra_pct: null, sem_rastreio_pct: null, nao_atribuido_pct: null },
};

describe("traffic-summary", () => {
  it("formata nulo como travessão", () => {
    expect(fmtBRLOrDash(null)).toBe("—");
    expect(fmtPctOrDash(null)).toBe("—");
    expect(fmtRoasOrDash(null)).toBe("—");
    expect(fmtDays(null)).toBe("—");
  });
  it("formata valores", () => {
    expect(fmtBRLOrDash(1234.5)).toBe("R$ 1.234,50");
    expect(fmtPctOrDash(0.4936)).toBe("49.4%");
    expect(fmtRoasOrDash(3)).toBe("3,0x");
    expect(fmtDays(1)).toBe("1 dia");
    expect(fmtDays(7.5)).toBe("7,5 dias");
  });
  it("monta a linha do bloco recolhido", () => {
    expect(collapsedLine(base)).toBe("1.240 leads → 612 conversas → 188 closer → 41 clientes");
  });
});
