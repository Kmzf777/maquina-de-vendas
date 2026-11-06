/**
 * Motivo de perda estruturado (frente F4, 06/11/2026).
 *
 * Mesma lista e ordem do CHECK em `supabase/migrations/20261106_f4_deals_lost_reason_code.sql`
 * e de `backend/app/leads/motivo_perda.py` (o teste do backend lê este arquivo e confere).
 * `deals.lost_reason` continua livre, agora como observação.
 */
import type { PipelineStage } from "./types";

export const LOST_REASONS = [
  { code: "preco_margem", label: "Preço / margem não fechou" },
  { code: "frete", label: "Frete" },
  { code: "pedido_minimo", label: "Pedido mínimo alto" },
  { code: "condicao_bonificacao", label: "Faltou condição / bonificação" },
  { code: "comprou_outro", label: "Comprou de outro fornecedor" },
  { code: "ainda_pesquisando", label: "Ainda pesquisando" },
  { code: "consumidor_final", label: "Era consumidor final (uso próprio)" },
  { code: "sem_resposta", label: "Sem resposta" },
  { code: "outro", label: "Outro" },
] as const;

export type LostReasonCode = (typeof LOST_REASONS)[number]["code"];

/** O que o modal devolve e o PATCH do deal grava. */
export interface LostReasonValue {
  lost_reason_code: LostReasonCode;
  lost_competitor: string | null;
  /** Observação livre (deals.lost_reason). */
  lost_reason: string | null;
}

export const LOST_COMPETITOR_MAX = 120;

const CODES = new Set<string>(LOST_REASONS.map((r) => r.code));

export function isLostReasonCode(v: unknown): v is LostReasonCode {
  return typeof v === "string" && CODES.has(v);
}

export function lostReasonLabel(code: string | null | undefined): string | null {
  return LOST_REASONS.find((r) => r.code === code)?.label ?? null;
}

/** Etapas de perda: as mesmas keys que o backend resolve em `_perdido_stage_id`. */
export const LOST_STAGE_KEYS = ["fechado_perdido", "perdido"] as const;

export function isLostStage(stage: Pick<PipelineStage, "key"> | null | undefined): boolean {
  return !!stage?.key && (LOST_STAGE_KEYS as readonly string[]).includes(stage.key);
}

/**
 * Valida o que o usuário preencheu. Devolve a mensagem de erro (pt-BR) ou null.
 * Motivo é obrigatório; concorrente é obrigatório quando o motivo é "comprou_outro".
 */
export function validateLostReason(code: string, competitor: string): string | null {
  if (!isLostReasonCode(code)) return "Escolha o motivo da perda.";
  if (code === "comprou_outro" && !competitor.trim()) return "Diga de quem o lead comprou.";
  return null;
}

/** Monta o valor final (limpa espaços; concorrente só acompanha "comprou_outro"). */
export function buildLostReason(code: LostReasonCode, competitor: string, note: string): LostReasonValue {
  const comp = competitor.replace(/\s+/g, " ").trim().slice(0, LOST_COMPETITOR_MAX);
  const obs = note.trim();
  return {
    lost_reason_code: code,
    lost_competitor: code === "comprou_outro" && comp ? comp : null,
    lost_reason: obs || null,
  };
}

/**
 * Valida o corpo do PATCH de deal na rota da API. Devolve o erro (pt-BR) ou null.
 * Código ausente é aceito (outros caminhos ainda movem sem modal); código fora da lista não.
 */
export function validateLostReasonPatch(body: Record<string, unknown>): string | null {
  if (!("lost_reason_code" in body) || body.lost_reason_code === null) return null;
  if (!isLostReasonCode(body.lost_reason_code)) return "Motivo de perda inválido.";
  if (body.lost_reason_code === "comprou_outro") {
    const c = body.lost_competitor;
    if (typeof c !== "string" || !c.trim()) return "Diga de quem o lead comprou.";
  }
  return null;
}
