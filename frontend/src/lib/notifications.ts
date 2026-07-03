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

/**
 * Decide se o usuário logado pode ser notificado sobre uma mensagem do canal
 * `channelId`, dado o escopo retornado por `/api/me/allowed-channels`.
 *
 * Semântica de `allowed` (mesma de `getAllowedChannelIds`):
 * - `null`      => admin, sem restrição → sempre permitido.
 * - `string[]`  => vendedor → permitido apenas se o canal estiver na lista.
 * - `undefined` => escopo ainda não carregado (ou falhou) → fail-closed.
 *
 * Canal não resolvido (`channelId` ausente) também é fail-closed: nunca
 * notificar sem saber a quem a mensagem pertence.
 */
export function isChannelAllowed(
  channelId: string | null | undefined,
  allowed: string[] | null | undefined,
): boolean {
  if (allowed === undefined) return false;
  if (allowed === null) return true;
  if (!channelId) return false;
  return allowed.includes(channelId);
}

/** Encurta o texto do preview do toast, anexando reticências quando excede `max`. */
export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
}
