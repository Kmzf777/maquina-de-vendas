/**
 * Regras puras (testáveis) de notificação de novas mensagens no chat.
 * Mantidas fora do hook para rodarem no vitest (ambiente node, sem browser/Supabase).
 */

/**
 * Decide se uma mensagem recém-inserida deve gerar alerta sonoro + toast.
 *
 * Regra atual: notifica TODA mensagem do contato (`role === "user"`),
 * independente de a IA estar ligada ou desligada. Mensagens da própria IA
 * (`assistant`) e de sistema (`system`) nunca notificam.
 */
export function shouldNotifyForMessage(msg: { role?: string | null }): boolean {
  return msg.role === "user";
}

/** Encurta o texto do preview do toast, anexando reticências quando excede `max`. */
export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
}
