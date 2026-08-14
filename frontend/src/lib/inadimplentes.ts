import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

export interface LeadComTags {
  id: string;
  name: string | null;
  phone: string;
  lead_tags?: { tag_id: string; tags: { id: string; name: string; color: string } | null }[];
  metadata?: Record<string, unknown> | null;
}

export interface ResultadoInadimplentes {
  leads: LeadComTags[];
  totalVencido: number;
}

/**
 * Parse tolerante: o valor vem de `metadata` (jsonb), então pode chegar como
 * número, como string no formato brasileiro ("1.234,56") ou ausente. Nada aqui
 * pode lançar — um alerta que quebra a tela é pior que um alerta impreciso.
 */
function parseValor(bruto: unknown): number {
  if (typeof bruto === "number") return Number.isFinite(bruto) ? bruto : 0;
  if (typeof bruto !== "string") return 0;
  const normalizado = bruto.trim().replace(/\./g, "").replace(",", ".");
  const valor = Number.parseFloat(normalizado);
  return Number.isFinite(valor) ? valor : 0;
}

export function temDebitoVencido(lead: LeadComTags): boolean {
  return (lead.lead_tags ?? []).some((lt) => lt.tag_id === TAG_DEBITO_VENCIDO_ID);
}

/** Valor vencido de um lead, já parseado. Use isto na UI — nunca `Number(...)`
 *  direto sobre o metadata, que devolve NaN em "1.234,56". */
export function valorVencidoDe(lead: LeadComTags): number {
  return parseValor(lead.metadata?.valor_vencido);
}

/**
 * Quais dos leads SELECIONADOS têm a tag fixa de débito vencido.
 *
 * Leads tagueados à mão depois da importação não têm `valor_vencido` no
 * metadata — eles contam na lista e somam zero, nunca somem do aviso.
 */
export function findInadimplentes(
  leads: LeadComTags[],
  selectedIds: Set<string>
): ResultadoInadimplentes {
  const encontrados = leads.filter((l) => selectedIds.has(l.id) && temDebitoVencido(l));
  const totalVencido = encontrados.reduce(
    (soma, l) => soma + parseValor(l.metadata?.valor_vencido),
    0
  );
  return { leads: encontrados, totalVencido };
}
