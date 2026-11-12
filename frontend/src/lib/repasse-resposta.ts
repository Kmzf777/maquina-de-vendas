// Leitura de `public.vw_repasse_resposta` (migration 20261019_repasse_sla.sql):
// uma linha por lead repassado ao closer, com o tempo até o closer assumir em
// minutos ÚTEIS do vendedor (sla_seller_config + sla_overrides; padrão 10h–16h
// seg–sex). É a fonte única desse tempo nas telas — `first_response_at -
// created_at` media outra coisa (desde a entrada do lead, em horas corridas).
//
// Regra das telas: lead sem linha, ou view indisponível → "—". Nunca zero.
//
// Sem React aqui: a rota /api/leads/[id]/overview importa este módulo. O hook
// de um lead mora em hooks/use-repasse-resposta.ts.

import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * Estado da resposta ao repasse (migration 20261106_repasse_estado_resposta.sql; definição
 * comum F2/F6 de 06/11/2026). Só `vendedor_nao_respondeu` é falha do vendedor; `sem_contato`
 * é falha do sistema (repasse sem contato automático do vendedor).
 */
export type EstadoResposta =
  | "vendedor_respondeu"
  | "lead_nao_respondeu"
  | "em_aberto"
  | "vendedor_nao_respondeu"
  | "sem_contato";

export interface RepasseResposta {
  lead_id: string;
  repasse_em: string;
  vendedor_id: string | null;
  primeira_resposta_em: string | null;
  minutos_uteis: number | null;
  minutos_uteis_em_aberto: number | null;
  respondeu: boolean;
  // F2: opcionais porque a view antiga (antes da migration 20261106) não as tem.
  estado?: EstadoResposta | null;
  espera_desde?: string | null;
  minutos_uteis_espera?: number | null;
  fora_do_crm?: boolean | null;
}

const VIEW = "vw_repasse_resposta";
const LOTE_IDS = 200;

/** D4/D6: tempo até o closer assumir, em minutos úteis do vendedor, a partir do 1º repasse. */
export async function fetchRepasseResposta(
  sb: SupabaseClient,
  leadIds: string[],
): Promise<Map<string, RepasseResposta>> {
  const out = new Map<string, RepasseResposta>();
  for (let i = 0; i < leadIds.length; i += LOTE_IDS) {
    const { data, error } = await sb.from(VIEW).select("*").in("lead_id", leadIds.slice(i, i + LOTE_IDS));
    if (error) throw error;
    for (const r of (data ?? []) as RepasseResposta[]) out.set(r.lead_id, r);
  }
  return out;
}

export function formatarMinutos(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m < 60) return `${Math.round(m)} min`;
  const h = Math.floor(m / 60),
    r = Math.round(m % 60);
  return r ? `${h}h ${r}min` : `${h}h`;
}

export interface DescricaoEstado {
  texto: string;
  /** Falha (do vendedor ou do sistema): a tela pinta de vermelho. */
  falha: boolean;
}

/**
 * Uma linha para o cartão "Tempo até o closer assumir", pelo estado da view.
 * `null` = nada a dizer além do tempo (vendedor respondeu, ou lead sem repasse).
 * View antiga (sem `estado`): o "Aguardando há" de antes.
 */
export function descreverEstado(r: RepasseResposta | null | undefined): DescricaoEstado | null {
  if (!r) return null;
  if (r.fora_do_crm && r.estado !== "vendedor_respondeu") {
    return { texto: "Vendedor atende fora do CRM", falha: false };
  }
  const espera = r.minutos_uteis_espera == null ? null : Number(r.minutos_uteis_espera);
  switch (r.estado) {
    case "vendedor_respondeu":
      return null;
    case "lead_nao_respondeu":
      return { texto: "Lead não respondeu ao vendedor", falha: false };
    case "em_aberto":
      return espera == null
        ? { texto: "Em aberto: contato do vendedor agendado", falha: false }
        : { texto: `Em aberto: lead espera há ${formatarMinutos(espera)} úteis`, falha: false };
    case "vendedor_nao_respondeu":
      return { texto: `Vendedor não respondeu: lead espera há ${formatarMinutos(espera)} úteis`, falha: true };
    case "sem_contato":
      return { texto: "Sem contato do vendedor (falha do sistema)", falha: true };
    default:
      if (r.respondeu || r.minutos_uteis_em_aberto == null) return null;
      return { texto: `Aguardando há ${formatarMinutos(Number(r.minutos_uteis_em_aberto))}`, falha: false };
  }
}

export interface ResumoTempoCloser {
  amostras: number;
  media: number | null;
  mediana: number | null;
}

/** Média e mediana de `minutos_uteis` dos leads da lista que o closer já assumiu. */
export function resumirTempoCloser(mapa: Map<string, RepasseResposta>, leadIds: string[]): ResumoTempoCloser {
  const valores: number[] = [];
  for (const id of leadIds) {
    const r = mapa.get(id);
    if (!r || !r.respondeu || r.minutos_uteis == null) continue;
    const n = Number(r.minutos_uteis);
    if (Number.isFinite(n)) valores.push(n);
  }
  if (valores.length === 0) return { amostras: 0, media: null, mediana: null };
  valores.sort((a, b) => a - b);
  const meio = Math.floor(valores.length / 2);
  const mediana = valores.length % 2 ? valores[meio] : (valores[meio - 1] + valores[meio]) / 2;
  const media = valores.reduce((s, v) => s + v, 0) / valores.length;
  return { amostras: valores.length, media, mediana };
}

/** O que o painel do lead (/api/leads/[id]/overview) carrega da view. */
export interface OverviewRepasse {
  repasse_em: string | null;
  minutos_uteis: number | null;
  respondeu: boolean;
}

/** Linha crua da view → payload do overview. `numeric` do Postgres pode chegar como string. */
export function mapRepasseOverview(row: Record<string, unknown> | null | undefined): OverviewRepasse | null {
  if (!row) return null;
  const n = row.minutos_uteis == null ? null : Number(row.minutos_uteis);
  return {
    repasse_em: typeof row.repasse_em === "string" ? row.repasse_em : null,
    minutos_uteis: n != null && Number.isFinite(n) ? n : null,
    respondeu: row.respondeu === true,
  };
}
