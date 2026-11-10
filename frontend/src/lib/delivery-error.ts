/**
 * Texto do motivo de não-entrega, em pt-BR, para a bolha do vendedor.
 * O backend grava o erro da Meta em messages.metadata.delivery_error
 * (meta_router._record_delivery_error) quando o status vira 'failed'.
 */
type Status = "accepted" | "sent" | "delivered" | "read" | "failed" | "undelivered" | null | undefined;

const POR_CODIGO: Record<number, string> = {
  131026: "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou.",
  131047: "Não entregue: passou a janela de 24h. Só dá para enviar modelo aprovado.",
  131042: "Não entregue: problema de pagamento na conta da Meta.",
  131049: "Não entregue: a Meta limitou mensagens de marketing para este cliente.",
};

export function deliveryErrorText(status: Status, metadata: Record<string, unknown> | null | undefined): string | null {
  if (status === "undelivered") return "Entrega não confirmada pela Meta.";
  if (status !== "failed") return null;
  const err = (metadata?.delivery_error ?? null) as { code?: number | string | null; title?: string | null } | null;
  const code = err?.code != null ? Number(err.code) : null;
  if (code == null || Number.isNaN(code)) return "Não entregue (motivo não registrado).";
  if (POR_CODIGO[code]) return POR_CODIGO[code];
  return `Não entregue: ${err?.title || "erro da Meta"} (código ${code}).`;
}
