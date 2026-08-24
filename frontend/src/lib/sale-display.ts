/** Derivações de exibição da venda (status e link do pedido no Bling). */
import type { Sale } from "@/lib/types";

/**
 * O deep-link do pedido NÃO está documentado no OpenAPI do Bling. Confirme o
 * formato abrindo um pedido real no Bling e ajuste esta constante — é o único
 * lugar do código que precisa mudar.
 */
export const BLING_ORDER_URL_TEMPLATE =
  "https://www.bling.com.br/vendas.php#edit/{id}";

export type StatusTone = "neutral" | "warning" | "danger";

export interface SaleStatus {
  label: string;
  tone: StatusTone;
}

export function saleStatus(sale: Sale): SaleStatus {
  if (sale.status === "cancelada") return { label: "Cancelada", tone: "danger" };
  if (sale.status === "pendente_bling") return { label: "Enviando…", tone: "warning" };
  return { label: sale.bling_situacao_nome || "Registrada", tone: "neutral" };
}

export function orderLabel(sale: Sale): string {
  return sale.bling_order_number ? `#${sale.bling_order_number}` : "";
}

export function blingOrderUrl(orderId: number | null | undefined): string {
  return orderId ? BLING_ORDER_URL_TEMPLATE.replace("{id}", String(orderId)) : "";
}

/**
 * A venda esta fora do Bling? O discriminador e a AUSENCIA de pedido, nao o
 * `origin`: `bling_order_id IS NULL` e a unica condicao verdadeira para os tres
 * casos que estao de fato fora do ERP (venda anterior a integracao, venda da
 * escapatoria, venda legada) e falsa para os que estao dentro.
 */
export function foraDoBling(sale: Pick<Sale, "bling_order_id">): boolean {
  return !sale.bling_order_id;
}
