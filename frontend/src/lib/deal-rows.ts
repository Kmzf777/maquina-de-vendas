import type { Pipeline, PipelineStage } from "@/lib/types";

/** Keys das colunas terminais. Espelha o que o Kanban trata como fechamento. */
export const CLOSED_STAGE_KEYS = ["fechado_ganho", "fechado_perdido"];

/** Deal como vem de GET /api/leads/[id]/deals. */
export interface LeadDeal {
  id: string;
  title: string;
  value: number;
  category: string | null;
  stage_id: string | null;
  pipeline_id: string | null;
  updated_at: string;
  lost_reason: string | null;
  pipeline_stages: Pick<PipelineStage, "id" | "label" | "dot_color" | "key" | "is_protected"> | null;
  pipelines: Pick<Pipeline, "id" | "name"> | null;
}

/** Stage como vem de GET /api/pipelines/[id]/stages. */
export type StageOption = Pick<
  PipelineStage,
  "id" | "label" | "dot_color" | "order_index" | "is_protected"
>;

export type StagesByPipeline = Record<string, StageOption[]>;

export interface DealRow {
  deal: LeadDeal;
  isClosed: boolean;
  /** Só os stages não-protegidos do funil DESTE deal. Vazio => sem dropdown. */
  stageOptions: StageOption[];
  /** Rótulo do stage atual, exibido quando não há dropdown. */
  stageLabel: string;
  dotColor: string;
  pipelineName: string;
  /** Para onde "Reabrir" leva. null => não dá para reabrir. */
  reopenStageId: string | null;
  canEditStage: boolean;
}

/** Um deal está fechado se caiu numa coluna protegida — por key ou pela flag. */
export function isDealClosed(deal: LeadDeal): boolean {
  const stage = deal.pipeline_stages;
  if (!stage) return false;
  return stage.is_protected === true || CLOSED_STAGE_KEYS.includes(stage.key ?? "");
}

/** Funis distintos presentes nos deals — o que o painel precisa buscar. */
export function distinctPipelineIds(deals: LeadDeal[]): string[] {
  const ids = new Set<string>();
  for (const deal of deals) {
    if (deal.pipeline_id) ids.add(deal.pipeline_id);
  }
  return [...ids];
}

function firstOpenStageId(stages: StageOption[]): string | null {
  // order_index manda: a API já ordena, mas um cache remontado pode não estar
  // ordenado e reabrir no stage errado é um erro silencioso e caro.
  const open = stages.filter((s) => !s.is_protected);
  if (open.length === 0) return null;
  return open.reduce((a, b) => (a.order_index <= b.order_index ? a : b)).id;
}

/**
 * Monta uma linha por deal — abertos primeiro, cada grupo por updated_at desc.
 * Casa stage por deal.id, e não por pipeline_id: é o que torna dois deals
 * abertos no mesmo funil independentemente editáveis.
 */
export function buildDealRows(deals: LeadDeal[], stagesByPipeline: StagesByPipeline): DealRow[] {
  const rows = deals.map((deal) => {
    const stages = stagesByPipeline[deal.pipeline_id ?? ""] ?? [];
    const stageOptions = stages.filter((s) => !s.is_protected);
    const isClosed = isDealClosed(deal);
    return {
      deal,
      isClosed,
      stageOptions,
      stageLabel: deal.pipeline_stages?.label ?? "—",
      dotColor: deal.pipeline_stages?.dot_color || "#dedbd6",
      pipelineName: deal.pipelines?.name ?? "Sem funil",
      reopenStageId: isClosed ? firstOpenStageId(stages) : null,
      canEditStage: !isClosed && stageOptions.length > 0,
    };
  });

  return rows.sort((a, b) => {
    if (a.isClosed !== b.isClosed) return a.isClosed ? 1 : -1;
    return b.deal.updated_at.localeCompare(a.deal.updated_at);
  });
}

/**
 * Patch de reabertura. PATCH /api/deals/[id] grava closed_at ao entrar em stage
 * protegido mas nunca limpa ao sair — sem estes nulls, todo deal reaberto fica
 * com closed_at e lost_reason antigos. O route faz {...body}, então isto
 * resolve sem tocar no backend.
 */
export function reopenPatch(stageId: string): Record<string, unknown> {
  return { stage_id: stageId, closed_at: null, lost_reason: null };
}
