/**
 * Tipos de `lead_events` gravados pelos triggers da linha do tempo
 * (`supabase/migrations/20261006b_lead_timeline_triggers.sql`) e pelo backend
 * (mesclagem, atribuição manual). São milhares por lead ativo: a aba de notas e o
 * overview, que listam `lead_events` como "eventos do sistema", os deixam de fora —
 * quem mostra esses eventos é a linha do tempo (`/api/leads/[id]/timeline`).
 */
export const TIPOS_DA_LINHA_DO_TEMPO = [
  "entrada",
  "etapa",
  "venda",
  "venda_cancelada",
  "disparo",
  "mesclagem",
  "atribuicao_manual",
] as const;

/** Valor para `.not("event_type", "in", ...)` do PostgREST. */
export const FILTRO_TIPOS_DA_LINHA_DO_TEMPO = `(${TIPOS_DA_LINHA_DO_TEMPO.join(",")})`;
