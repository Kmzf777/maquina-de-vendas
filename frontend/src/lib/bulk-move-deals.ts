import type { PipelineStage } from "./types";

/** Quantas PATCHes rodam em paralelo por lote. Cada PATCH faz 3 round-trips no
 *  Supabase e dispara um webhook de automação — mandar 50 de uma vez martela o
 *  backend sem necessidade. */
export const MOVE_BATCH_SIZE = 5;

export interface MoveResult {
  id: string;
  ok: boolean;
  error?: string;
}

export interface MoveSummary {
  moved: number;
  failed: number;
  failedIds: string[];
  message: string;
}

/**
 * Corpo do PATCH para mover um deal. `pipeline_id` só entra quando o funil muda:
 * mandar o mesmo valor de volta faria a rota rodar a guarda de destino à toa.
 */
export function buildMovePayload(
  deal: { pipeline_id: string | null },
  targetPipelineId: string,
  targetStageId: string
): Record<string, string> {
  const payload: Record<string, string> = { stage_id: targetStageId };
  if (deal.pipeline_id !== targetPipelineId) payload.pipeline_id = targetPipelineId;
  return payload;
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export function summarizeMoveResults(results: MoveResult[]): MoveSummary {
  const failures = results.filter((r) => !r.ok);
  const moved = results.length - failures.length;
  if (failures.length === 0) {
    return { moved, failed: 0, failedIds: [], message: "" };
  }
  const reasons = [...new Set(failures.map((f) => f.error || "Erro desconhecido"))];
  return {
    moved,
    failed: failures.length,
    failedIds: failures.map((f) => f.id),
    message: `${moved} de ${results.length} deals movidos. ${failures.length} falharam: ${reasons.join("; ")}`,
  };
}

/**
 * Etapas oferecidas como destino: só as ativas. A etapa atual entra mesmo se for
 * protegida, senão o select mostraria outra etapa e mentiria sobre onde o deal está.
 */
export function selectableStages(
  stages: PipelineStage[],
  currentStageId: string | null
): PipelineStage[] {
  return stages.filter((s) => !s.is_protected || s.id === currentStageId);
}
