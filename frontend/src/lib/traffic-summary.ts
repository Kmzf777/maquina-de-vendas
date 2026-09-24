// Contrato de `summary` devolvido por GET /api/traffic/report (backend: build_report_summary).
// Taxas são frações 0..1; null = denominador zero (exibir "—", nunca 0).

export type SummaryStage = "conversa" | "closer" | "cliente";

export type StageRates = {
  taxa_conversa: number | null;
  taxa_closer: number | null;
  taxa_cliente: number | null;
  taxa_total: number | null;
};

export type StageCounts = { leads: number; conversas: number; closer: number; clientes: number };

export type SummaryFunnel = StageCounts & StageRates & { gargalo: SummaryStage | null };

export type SummaryCost = StageCounts & {
  investimento: number; receita: number; roas: number | null;
  cpl: number | null; custo_conversa: number | null; custo_closer: number | null; cac: number | null;
};

export type SummaryChannel = StageCounts & StageRates & {
  channel: string; receita: number; investimento: number; roas: number | null;
};

export type SummaryTiming = {
  dias_ate_compra_mediana: number | null;
  amostra_dias: number;
  pedidos_por_cliente: number | null;
  recompra_pct: number | null;
  sem_rastreio_pct: number | null;
  nao_atribuido_pct: number | null;
};

export type ReportSummary = {
  funnel: SummaryFunnel;
  cost: SummaryCost;
  channels: SummaryChannel[];
  timing_quality: SummaryTiming;
};

export const STAGE_LABEL: Record<SummaryStage, string> = {
  conversa: "Lead → Conversa",
  closer: "Conversa → Closer",
  cliente: "Closer → Cliente",
};

const DASH = "—";

export const fmtInt = (v: number) => v.toLocaleString("pt-BR");

export const fmtBRLOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const fmtPctOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `${(v * 100).toFixed(1)}%`;

export const fmtRoasOrDash = (v: number | null | undefined) =>
  v == null ? DASH : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`;

export const fmtDays = (v: number | null | undefined) => {
  if (v == null) return DASH;
  if (v === 1) return "1 dia";
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} dias`;
};

export const collapsedLine = (s: ReportSummary) => {
  const f = s.funnel;
  return `${fmtInt(f.leads)} leads → ${fmtInt(f.conversas)} conversas → ${fmtInt(f.closer)} closer → ${fmtInt(f.clientes)} clientes`;
};
