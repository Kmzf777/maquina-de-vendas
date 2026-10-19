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

export interface RepasseResposta {
  lead_id: string;
  repasse_em: string;
  vendedor_id: string | null;
  primeira_resposta_em: string | null;
  minutos_uteis: number | null;
  minutos_uteis_em_aberto: number | null;
  respondeu: boolean;
}

const VIEW = "vw_repasse_resposta";
const LOTE_IDS = 200;
const PAGINA = 1000;

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

/**
 * A view inteira, paginada (o PostgREST corta em 1.000 linhas). Para telas que
 * mostram todos os leads e filtram no cliente (Kanban): busca uma vez e o filtro
 * não dispara nova consulta.
 */
export async function fetchRepasseRespostaTodas(sb: SupabaseClient): Promise<Map<string, RepasseResposta>> {
  const out = new Map<string, RepasseResposta>();
  for (let de = 0; ; de += PAGINA) {
    const { data, error } = await sb
      .from(VIEW)
      .select("*")
      .order("lead_id")
      .range(de, de + PAGINA - 1);
    if (error) throw error;
    const linhas = (data ?? []) as RepasseResposta[];
    for (const r of linhas) out.set(r.lead_id, r);
    if (linhas.length < PAGINA) break;
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
