/** Resultado da resolução de escopo de canais para a busca de mensagens. */
export type SearchChannelScope =
  | { kind: "all" }
  | { kind: "ids"; ids: string[] }
  | { kind: "empty" };

/**
 * Resolve quais canais a busca pode cobrir, dado o escopo do usuário e um
 * channel_id opcional vindo do cliente. Um vendedor NUNCA busca fora dos seus
 * canais: channel_id não permitido => "empty".
 *
 * @param allowed null = admin (todos); string[] = restrito; [] = sem canais.
 * @param requested channel_id do query param (ou null).
 */
export function resolveSearchChannelScope(
  allowed: string[] | null,
  requested: string | null,
): SearchChannelScope {
  if (allowed === null) {
    return requested ? { kind: "ids", ids: [requested] } : { kind: "all" };
  }
  if (allowed.length === 0) return { kind: "empty" };
  if (requested) {
    return allowed.includes(requested)
      ? { kind: "ids", ids: [requested] }
      : { kind: "empty" };
  }
  return { kind: "ids", ids: allowed };
}
