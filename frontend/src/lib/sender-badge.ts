/** Rótulo do remetente para a bolha de mensagem. followup → "Cadência" (distinto da IA). */
export function senderBadge(
  message: { role: string; sent_by?: string | null }
): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  if (message.sent_by === "followup") return "Cadência";
  return null;
}
