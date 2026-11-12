/**
 * Endereço WhatsApp ENTREGÁVEL do lead — espelho de `resolve_send_target`
 * (backend/app/leads/service.py). Manter os dois iguais.
 *
 * `leads.phone` é normalizado e ganha o 9º dígito; números fixos (e alguns celulares
 * antigos) estão registrados na Meta SEM ele. Enviar para o `phone` faz a Meta aceitar
 * (HTTP 200 + wamid) e depois falhar com 131026 "Message undeliverable" — o caso da
 * Carolaine/MVX (phone 5537932140027, wa_id 553732140027), 06/11/2026.
 *
 * `requireInboundProvenance` (caminho frio, ex.: modelo como 1º contato): o wa_id só
 * vale se o lead já provou tráfego (wa_id_confirmed_at ou last_customer_message_at).
 */
export interface SendTargetLead {
  phone?: string | null;
  wa_id?: string | null;
  wa_id_confirmed_at?: string | null;
  last_customer_message_at?: string | null;
  bsuid?: string | null;
}

/** Colunas de `leads` que o helper precisa — use no select embutido das rotas. */
export const LEAD_SEND_FIELDS = "phone, wa_id, wa_id_confirmed_at, last_customer_message_at, bsuid";

export function hasWaIdProvenance(lead: SendTargetLead): boolean {
  return Boolean(lead.wa_id_confirmed_at) || Boolean(lead.last_customer_message_at);
}

export function resolveSendTarget(
  lead: SendTargetLead | null | undefined,
  opts: { requireInboundProvenance?: boolean } = {},
): string {
  if (!lead) return "";
  const waId = lead.wa_id;
  if (waId && (!opts.requireInboundProvenance || hasWaIdProvenance(lead))) return waId;
  return lead.phone || lead.bsuid || "";
}
