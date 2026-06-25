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

export interface HighlightSegment {
  text: string;
  match: boolean;
}

/** Remove acentos para comparação (NFD + strip das marcas combinantes U+0300–U+036F),
 *  mantendo o índice 1:1. */
function stripAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/**
 * Quebra `content` em segmentos marcando onde `query` casa (acento/caixa-insensível).
 * O texto de cada segmento é SEMPRE o original (acentos preservados na exibição).
 */
export function highlightSegments(content: string, query: string): HighlightSegment[] {
  const q = query.trim();
  if (!q) return [{ text: content, match: false }];

  const haystack = stripAccents(content).toLowerCase();
  const needle = stripAccents(q).toLowerCase();
  if (!needle) return [{ text: content, match: false }];

  const segments: HighlightSegment[] = [];
  let from = 0;
  let idx = haystack.indexOf(needle, from);
  if (idx === -1) return [{ text: content, match: false }];

  while (idx !== -1) {
    if (idx > from) segments.push({ text: content.slice(from, idx), match: false });
    segments.push({ text: content.slice(idx, idx + needle.length), match: true });
    from = idx + needle.length;
    idx = haystack.indexOf(needle, from);
  }
  if (from < content.length) segments.push({ text: content.slice(from), match: false });
  return segments;
}
