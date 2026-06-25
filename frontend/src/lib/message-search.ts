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

/**
 * Constrói uma versão "dobrada" (minúscula, sem acentos) de `s` junto com um mapa
 * folded-index -> índice (em code units) no `s` ORIGINAL. Iterar por code point e
 * registrar, para cada unidade do trecho dobrado, a posição inicial do caractere
 * original que a gerou — assim os slices sempre saem da string original alinhados,
 * mesmo com acentos antes do match ou pares substitutos (emoji).
 */
function buildFolded(s: string): { folded: string; map: number[] } {
  let folded = "";
  const map: number[] = [];
  let unit = 0;
  for (const ch of s) {
    const stripped = ch.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    const piece = stripped || ch.toLowerCase(); // marca combinante isolada: mantém
    for (let i = 0; i < piece.length; i++) map.push(unit);
    folded += piece;
    unit += ch.length; // code units consumidos no original
  }
  map.push(s.length); // sentinela: fim
  return { folded, map };
}

/**
 * Quebra `content` em segmentos marcando onde `query` casa (acento/caixa-insensível).
 * O texto de cada segmento é SEMPRE o original (acentos preservados na exibição) e
 * os índices ficam alinhados via mapa de posições.
 */
export function highlightSegments(content: string, query: string): HighlightSegment[] {
  const q = query.trim();
  if (!q) return [{ text: content, match: false }];

  const { folded, map } = buildFolded(content);
  const needle = buildFolded(q).folded;
  if (!needle) return [{ text: content, match: false }];

  const segments: HighlightSegment[] = [];
  let from = 0; // índice (code units) no content original
  let fIdx = folded.indexOf(needle, 0);
  if (fIdx === -1) return [{ text: content, match: false }];

  while (fIdx !== -1) {
    const start = map[fIdx];
    const end = map[fIdx + needle.length];
    if (start > from) segments.push({ text: content.slice(from, start), match: false });
    segments.push({ text: content.slice(start, end), match: true });
    from = end;
    fIdx = folded.indexOf(needle, fIdx + needle.length);
  }
  if (from < content.length) segments.push({ text: content.slice(from), match: false });
  return segments;
}
