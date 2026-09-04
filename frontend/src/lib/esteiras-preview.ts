/**
 * Monta os argumentos da RPC `get_deals_stage_stagnant` para a PRÉVIA de quantos cards
 * ficam elegíveis no instante em que uma esteira for ligada.
 *
 * Por que existe: `deals.entered_stage_at` é preenchida no backfill com a data da última
 * movimentação de cada card (20260904_esteiras_vendedor.sql, bloco 1). No segundo em que a
 * esteira de reposição for ligada, todo card parado há mais de 15 dias fica elegível de
 * uma vez. Esse número tem de aparecer ANTES do clique confirmar — depois já é avalanche.
 *
 * A prévia usa a MESMA RPC que o gatilho (`triggers.py::check_polling_triggers`), com os
 * mesmos parâmetros, trocando só o que o usuário mudou na tela e ainda não salvou. Uma
 * consulta paralela em PostgREST daria um número parecido e errado — silêncio de conversa
 * depende de um MAX(created_at) por lead que só a RPC resolve.
 */

/** Config do nó de gatilho, como gravada em `campaign_nodes.config`. */
export interface GatilhoConfig {
  stage_id?: string | null;
  stage_key?: string | null;
  pipeline_id?: string | null;
  stage_days?: number | null;
  silence_days?: number | null;
  last_speaker?: string | null;
}

/** O que a tela tem na mão no momento do clique (pode divergir do que está salvo). */
export interface PreviewOverrides {
  canal_id?: string | null;
  funil_id?: string | null;
  etapa_id?: string | null;
  dias?: number | null;
}

export interface RpcArgs {
  p_stage_id: string | null;
  p_stage_key: string | null;
  p_pipeline_id: string | null;
  p_channel_id: string | null;
  p_stage_days: number;
  p_silence_days: number;
  p_last_speaker: string;
  p_audience: string;
  p_limit: number;
}

/** Teto da prévia. Acima disso o número vira "mais de 500" — contar tudo não muda a decisão. */
export const PREVIEW_LIMIT = 500;

const num = (v: unknown, fallback = 0): number =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;

const str = (v: unknown): string | null =>
  typeof v === "string" && v.trim() !== "" ? v : null;

export function buildPreviewArgs(
  gatilho: GatilhoConfig,
  overrides: PreviewOverrides,
  audience: string | null | undefined
): RpcArgs {
  // Qual relógio o primeiro toque usa depende da esteira: a de proposta conta dias na
  // ETAPA, as outras contam dias de SILÊNCIO. Mesma regra do PUT em esteiras_router.py —
  // preserva o que o seed definiu em vez de adivinhar pelo valor da tela.
  const usaRelogioDeEtapa = num(gatilho.stage_days) > 0;
  const dias = overrides.dias == null ? null : num(overrides.dias);

  return {
    p_stage_id: str(overrides.etapa_id) ?? str(gatilho.stage_id),
    p_stage_key: str(gatilho.stage_key),
    p_pipeline_id: str(overrides.funil_id) ?? str(gatilho.pipeline_id),
    p_channel_id: str(overrides.canal_id),
    p_stage_days: usaRelogioDeEtapa && dias !== null ? dias : num(gatilho.stage_days),
    p_silence_days: !usaRelogioDeEtapa && dias !== null ? dias : num(gatilho.silence_days),
    p_last_speaker: str(gatilho.last_speaker) ?? "qualquer",
    // Nunca cai em 'ambos': o modo mais permissivo jamais pode ser resultado de dado
    // faltando. Espelha `engine._audience_allows`.
    p_audience: str(audience) ?? "ia",
    p_limit: PREVIEW_LIMIT,
  };
}

/**
 * Sem etapa (nem por id, nem por key) a RPC trata "qualquer etapa" — a prévia contaria
 * todo card aberto de todo funil e diria um número que não é o da esteira. Preferimos
 * não responder a responder errado.
 */
export function faltaEtapa(args: RpcArgs): boolean {
  return args.p_stage_id === null && args.p_stage_key === null;
}
