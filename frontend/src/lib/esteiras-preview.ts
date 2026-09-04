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
 *
 * "Os mesmos parâmetros" inclui `p_campaign_id`. Ele é opcional no SQL, então esquecê-lo
 * não levanta erro nenhum — só desliga o cooldown e faz a prévia contar cards que o
 * gatilho vai descartar. Qualquer parâmetro novo da RPC tem de chegar aqui junto.
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
  /**
   * Qual campanha está perguntando. Não é um override de configuração — é identidade —
   * mas viaja junto porque a tela já o tem no payload do GET e a RPC precisa dele para
   * aplicar o COOLDOWN. Ver `p_campaign_id` em RpcArgs.
   */
  campaign_id?: string | null;
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
  /**
   * Campanha que está perguntando. A RPC a usa para excluir o card que já passou por
   * ESTA campanha dentro do cooldown (`p_cooldown_days`, DEFAULT 90 —
   * 20260904_esteiras_vendedor.sql).
   *
   * Tem `DEFAULT NULL` no SQL, então omiti-lo não quebra nada: só desliga a exclusão em
   * silêncio, e a prévia passa a contar cards que o gatilho vai descartar. Um número
   * inflado aqui é pior do que parece — é o anteparo contra a avalanche do primeiro dia
   * e é o que o dono olha antes de confirmar "Ligar".
   *
   * `p_cooldown_days` fica de fora de propósito: `triggers.py` também não o passa, então
   * os dois herdam o mesmo default e não podem divergir.
   */
  p_campaign_id: string | null;
}

/** Teto da prévia. Acima disso o número vira "mais de 500" — contar tudo não muda a decisão. */
export const PREVIEW_LIMIT = 500;

const num = (v: unknown, fallback = 0): number =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;

const str = (v: unknown): string | null =>
  typeof v === "string" && v.trim() !== "" ? v : null;

/** Os dois relógios possíveis do primeiro toque, como `esteiras_router._relogio` os nomeia. */
export type Relogio = "stage_days" | "silence_days";

export function buildPreviewArgs(
  gatilho: GatilhoConfig,
  overrides: PreviewOverrides,
  audience: string | null | undefined,
  relogio?: string | null
): RpcArgs {
  // Qual relógio o primeiro toque usa depende da esteira: a de proposta conta dias na
  // ETAPA, as outras contam dias de SILÊNCIO.
  //
  // O valor autoritativo é o `relogio` que o backend devolve — ele sai do SEED, não do
  // estado atual do gatilho. Inferir de `stage_days > 0`, como esta função fazia antes,
  // tem um modo de falha real: gravar `dias: 0` uma vez zera `stage_days` e a inferência
  // passa a dizer "silêncio", trocando o relógio da esteira de proposta em silêncio.
  // A inferência sobrou só como rede para chamador que não informe o campo.
  const usaRelogioDeEtapa =
    relogio === "stage_days" || relogio === "silence_days"
      ? relogio === "stage_days"
      : num(gatilho.stage_days) > 0;
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
    p_campaign_id: str(overrides.campaign_id),
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
