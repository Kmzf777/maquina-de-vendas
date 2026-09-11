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
  "id" | "label" | "dot_color" | "order_index" | "is_protected" | "key"
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
  /**
   * O stage atual não pertence ao funil do deal. Acontece de verdade: a ação
   * `move_deal_stage` de cadência escolhe a etapa entre TODOS os funis e grava
   * só o stage_id (automation/engine.py). Sem sinalizar, o <select> não acha o
   * value e renderiza em branco num deal aberto.
   */
  stageOutsidePipeline: boolean;
  /**
   * Os stages deste funil ainda não chegaram (ou o fetch falhou). Diferente de
   * "funil sem etapas abertas": aqui não dá para afirmar nada ainda, e tratar
   * como read-only faria toda linha aberta piscar de texto para dropdown.
   */
  stagesUnknown: boolean;
}

/**
 * Uma etapa terminal. Checa a key ALÉM da flag porque is_protected é false em
 * todas as linhas do banco (012_multi_pipeline.sql:21 default false;
 * api/pipelines/route.ts semeia "Fechado Ganho"/"Perdido" com false). Confiar só
 * na flag deixaria as etapas de fechamento no dropdown do painel, onde não há
 * captura de motivo de perda.
 */
export function isClosingStage(stage: { key: string | null; is_protected: boolean }): boolean {
  return stage.is_protected === true || CLOSED_STAGE_KEYS.includes(stage.key ?? "");
}

/** Um deal está fechado se caiu numa coluna protegida — por key ou pela flag. */
export function isDealClosed(deal: LeadDeal): boolean {
  const stage = deal.pipeline_stages;
  if (!stage) return false;
  return isClosingStage(stage);
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
  const open = stages.filter((s) => !isClosingStage(s));
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
    const pipelineId = deal.pipeline_id ?? "";
    const stages = stagesByPipeline[pipelineId] ?? [];
    const stageOptions = stages.filter((s) => !isClosingStage(s));
    const isClosed = isDealClosed(deal);
    const canEditStage = !isClosed && stageOptions.length > 0;
    return {
      deal,
      isClosed,
      stageOptions,
      stageLabel: deal.pipeline_stages?.label ?? "—",
      dotColor: deal.pipeline_stages?.dot_color || "#dedbd6",
      pipelineName: deal.pipelines?.name ?? "Sem funil",
      reopenStageId: isClosed ? firstOpenStageId(stages) : null,
      canEditStage,
      stageOutsidePipeline:
        canEditStage && !stageOptions.some((s) => s.id === deal.stage_id),
      // Só é "desconhecido" se o deal tem funil: sem pipeline_id não há o que
      // carregar, e a linha é read-only de forma definitiva.
      stagesUnknown: pipelineId !== "" && !(pipelineId in stagesByPipeline),
    };
  });

  return rows.sort((a, b) => {
    if (a.isClosed !== b.isClosed) return a.isClosed ? 1 : -1;
    if (a.deal.updated_at === b.deal.updated_at) return 0;
    return a.deal.updated_at < b.deal.updated_at ? 1 : -1;
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
