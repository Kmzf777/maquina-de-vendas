// Modo do /trafego e a linha de status do sync de investimento.
// Padrão "periodo" (12/11/2026) na página, nos proxies e no backend: cada coluna conta pela própria
// data — leads e closer de quem entrou no período, pedidos e receita de toda venda do período.
// Antes era escolher entre "por lead" (05–11/11: 1 cliente de 53 pedidos) e "por venda" (o Meta
// Atacado com 0 leads de 64). "lead" (por turma) segue como opção; "sale" só para link antigo.

export type TrafficMode = "periodo" | "lead" | "sale";

export const MODO_PADRAO: TrafficMode = "periodo";

export const FRASE_MODO: Record<TrafficMode, string> = {
  periodo: "Leads e closer: quem entrou no período. Pedidos e receita: toda venda do período, de lead novo ou antigo",
  lead: "Por turma: só os leads que entraram no período e as vendas deles até 30 dias depois (90 no B2B)",
  sale: "Só quem comprou: toda venda do período, de lead novo ou antigo",
};

export function modoDaUrl(v: string | null | undefined): TrafficMode {
  return v === "periodo" || v === "lead" || v === "sale" ? v : MODO_PADRAO;
}

export type RodadaSync = { status: "ok" | "falha" | "aviso"; linhas?: number; motivo?: string | null; em: string };

const NOME: Record<string, string> = { google: "Google", meta: "Meta" };

function dataHora(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(d);
  const v = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${v("day")}/${v("month")} ${v("hour")}:${v("minute")}`;
}

/** "Google: sincronizado em 06/11 14:30", "Google: falhou em 06/11 14:30: HTTP 404" ou
 *  "Google: zerado em 06/11 14:30: <motivo>" (0 linhas em dia útil com campanha ativa). */
export function linhaSync(plataforma: string, r: RodadaSync): string {
  const nome = NOME[plataforma] ?? plataforma;
  const quando = dataHora(r.em);
  if (r.status === "ok") return `${nome}: sincronizado em ${quando}`;
  const verbo = r.status === "falha" ? "falhou" : "zerado";
  return `${nome}: ${verbo} em ${quando}${r.motivo ? `: ${r.motivo}` : ""}`;
}
