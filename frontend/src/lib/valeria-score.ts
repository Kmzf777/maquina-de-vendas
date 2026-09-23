export type SellerFeeling = "baixo" | "medio" | "alto";

export interface ValeriaScoreSnapshot {
  segment: string | null;
  monthly_volume_kg: number | null;
  supplier_reason: string | null;
  purchase_timing: string | null;
  purchase_intent: string | null;
  evidence: Record<string, unknown> | null;
  normal_score: number | null;
  final_score: number | null;
  priority: string | null;
  is_provisional: boolean;
  updated_at: string;
}

export interface ValeriaFeeling {
  feeling: SellerFeeling;
  justification: string;
  updated_at: string;
  user_id?: string;
  seller_email?: string | null;
}

export interface ValeriaScoreItem {
  id: string;
  name: string | null;
  phone: string | null;
  company: string | null;
  campaign: string | null;
  traffic_type: "paid" | "organic" | null;
  last_interaction_at: string | null;
  score: ValeriaScoreSnapshot | null;
  feeling: ValeriaFeeling | null;
  own_feeling: ValeriaFeeling | null;
}

export interface ValeriaScoreResponse {
  items: ValeriaScoreItem[];
  total: number;
  page: number;
  page_size: number;
  campaigns: string[];
  current_user_id: string;
  current_user_role: string | null;
}

export function priorityLabel(priority: string | null | undefined): string {
  return ({ low: "Baixa", moderate: "Moderada", high: "Alta", maximum: "Máxima" } as Record<string, string>)[priority ?? ""] ?? "Não identificado";
}

export function scoreLabel(score: number | null | undefined): string {
  if (score == null) return "—";
  if (score === 10) return "10 — Prioridade Máxima";
  return `${score}/8`;
}

export function scoreStatusLabel(isProvisional: boolean): string {
  return isProvisional ? "Provisório" : "Consolidado";
}

export function feelingValidationError(value: unknown): string | null {
  if (!value || typeof value !== "object") return "Dados de Feeling inválidos.";
  if (Object.keys(value).some((key) => key !== "feeling" && key !== "justification")) return "Dados de Feeling inválidos.";
  const { feeling, justification } = value as { feeling?: unknown; justification?: unknown };
  if (feeling !== "baixo" && feeling !== "medio" && feeling !== "alto") {
    return "Feeling inválido.";
  }
  if (typeof justification !== "string" || !justification.trim()) return "A justificativa é obrigatória.";
  if (justification.trim().length > 1000) return "A justificativa deve ter no máximo 1000 caracteres.";
  return null;
}
