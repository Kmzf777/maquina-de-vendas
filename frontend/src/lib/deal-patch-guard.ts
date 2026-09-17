/**
 * Decisão de qual funil vale num PATCH de deal — módulo puro, testável fora da rota.
 *
 * O `PATCH /api/deals/[id]` aceita `pipeline_id` e `stage_id` no mesmo corpo (mover de
 * funil e trocar de etapa de uma vez). Antes de escrever, a rota precisa saber contra
 * qual funil conferir a etapa; essa escolha é esta função.
 */

/** Funil que a etapa do corpo precisa respeitar: o destino, se houver; senão o atual. */
export function resolveEffectivePipelineId(
  body: { pipeline_id?: string | null },
  current: { pipeline_id: string | null }
): string | null {
  // Truthiness (e não `??`) de propósito: espelha o guard de destino da própria rota
  // (`if (body.pipeline_id && ...)`), então `null`, `undefined` e `""` no corpo todos
  // significam "não estou mudando de funil" e caem no funil atual do deal.
  if (body.pipeline_id) return body.pipeline_id;
  return current.pipeline_id ?? null;
}
