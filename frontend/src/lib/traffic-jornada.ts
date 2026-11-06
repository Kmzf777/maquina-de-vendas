/**
 * Jornada do lead no /trafego (frente F5, cartões B e C de
 * Canastra-Content-Creator/relatorios/crm-jornada-e-trafego-2026-11.md).
 *
 * O backend (`traffic_report.py`) devolve o relatório nas duas atribuições em `por_atribuicao`,
 * o bloco `jornadas` e o detalhe `sem_rastreio`. A tela só escolhe qual atribuição mostrar: os
 * totais de leads, vendas e receita são os mesmos nas duas, muda em que linha cada lead cai.
 */

export type Atribuicao = "ultima" | "primeira";

export const ATRIBUICOES: { value: Atribuicao; label: string; ajuda: string }[] = [
  { value: "ultima", label: "Última origem", ajuda: "A venda vai para o último canal antes dela" },
  { value: "primeira", label: "Primeira origem", ajuda: "A venda vai para o canal que trouxe o lead" },
];

export type Toque = { canal: string; em: string };

export type Jornada = {
  primeira_origem: string | null;
  primeira_em: string | null;
  ultima_origem: string | null;
  ultima_em: string | null;
  origens: string[];
  toques: Toque[];
  n_toques: number;
  multicanal: boolean;
  estimado: boolean;
};

export type CaminhoJornada = { caminho: string; leads: number; clientes: number; pedidos: number; receita: number };

export type JornadasResumo = {
  leads: number; clientes: number; pedidos: number; receita: number; total_leads: number;
  caminhos: CaminhoJornada[];
};

export type SemRastreioResumo = { leads: number; motivos: { motivo: string; leads: number }[] };

export type ParteAtribuida<R, T, S, M> = {
  rows: R[]; total: T; channel_subtotals: S; summary?: M; entraram_ja_clientes?: number;
};

type RelatorioComAtribuicao<R, T, S, M> = ParteAtribuida<R, T, S, M> & {
  por_atribuicao?: Partial<Record<Atribuicao, ParteAtribuida<R, T, S, M>>>;
};

/** A parte do relatório na atribuição pedida; backend sem F5 devolve o topo (comportamento antigo). */
export function escolherAtribuicao<R, T, S, M>(
  report: RelatorioComAtribuicao<R, T, S, M>,
  atribuicao: Atribuicao,
): ParteAtribuida<R, T, S, M> {
  return report.por_atribuicao?.[atribuicao] ?? report;
}

export const SETA = " → ";

/** "Meta Ads → Google Ads"; lead sem entrada mostra o canal estimado com "(estimado)". */
export function passouPorTexto(j: Jornada | null | undefined): string {
  if (!j || !j.origens?.length) return "—";
  const txt = j.origens.join(SETA);
  return j.estimado ? `${txt} (estimado)` : txt;
}

const fmtDia = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "America/Sao_Paulo" });
};

/** Tooltip: cada toque com a data ("Meta Ads em 01/10 · Google Ads em 09/10"). */
export function passouPorTooltip(j: Jornada | null | undefined): string | undefined {
  if (!j) return undefined;
  if (j.estimado || !j.toques?.length) return "Sem entrada na linha do tempo: canal estimado pelo cadastro";
  return j.toques.map((t) => `${t.canal} em ${fmtDia(t.em)}`).join(" · ");
}

const PARAMS_JORNADA = ["channel", "campaign", "period", "mode", "date_from", "date_to", "atribuicao"] as const;

/** Query do proxy /api/traffic/jornada/campaign: só os parâmetros conhecidos. */
export function jornadaCampaignQuery(url: string): string {
  const { searchParams } = new URL(url);
  const out = new URLSearchParams();
  for (const k of PARAMS_JORNADA) {
    const v = searchParams.get(k);
    if (v) out.set(k, v);
  }
  return out.toString();
}

/** Endpoint do detalhe: a "última" (padrão) usa a rota de sempre; a "primeira" vai à da jornada. */
export function detalheCampanhaUrl(qs: string, atribuicao: string | null | undefined): string {
  return atribuicao === "primeira" ? `/api/traffic/jornada/campaign?${qs}` : `/api/traffic/campaign?${qs}`;
}
