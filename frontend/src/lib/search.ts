/** Lowercases and strips diacritics (á→a, ç→c, ã→a) for accent-insensitive matching. */
export function foldText(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export interface LeadSearchFields {
  name?: string | null;
  phone?: string | null;
  company?: string | null;
  razao_social?: string | null;
  nome_fantasia?: string | null;
}

/**
 * True when `query` matches the lead by name/company/razao_social/nome_fantasia
 * (accent-insensitive substring) OR by phone (digit-substring, so formatted input
 * like "(34) 99999-8888" matches the stored 13-digit "5534999998888").
 * Empty/whitespace query matches everything.
 */
export function leadMatchesSearch(query: string, lead: LeadSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const q = foldText(raw);
  const textMatch = [lead.name, lead.company, lead.razao_social, lead.nome_fantasia].some(
    (field) => field != null && foldText(field).includes(q)
  );
  if (textMatch) return true;

  const qDigits = raw.replace(/\D/g, "");
  if (qDigits && lead.phone && lead.phone.replace(/\D/g, "").includes(qDigits)) return true;

  return false;
}

export interface DealSearchFields {
  title: string;
  leads?: LeadSearchFields | null;
}

/**
 * True when `query` matches o deal pelo título OU pelos campos do lead vinculado
 * (mesma lógica de `leadMatchesSearch`, accent-insensitive + telefone por dígitos).
 * Empty/whitespace query matches everything.
 */
export function dealMatchesSearch(query: string, deal: DealSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const q = foldText(raw);
  if (foldText(deal.title).includes(q)) return true;

  if (deal.leads && leadMatchesSearch(query, deal.leads)) return true;

  return false;
}

/**
 * Letras latinas e as variantes acentuadas que devem casar com elas. Serve de
 * substituto ao `unaccent()` do Postgres, que não está disponível como filtro
 * inline no PostgREST (exigiria uma migration/RPC só para a busca).
 */
const ACCENT_CLASSES: Record<string, string> = {
  a: "aàáâãäå",
  c: "cç",
  e: "eèéêë",
  i: "iìíîï",
  n: "nñ",
  o: "oòóôõö",
  u: "uùúûü",
  y: "yýÿ",
};

/** Colunas de texto do lead cobertas pela busca — espelha {@link leadMatchesSearch}. */
const LEAD_TEXT_COLUMNS = ["name", "company", "razao_social", "nome_fantasia"] as const;

/**
 * Constrói um padrão POSIX para o operador `imatch` (`~*`) do PostgREST que casa
 * `query` ignorando acentos NOS DOIS SENTIDOS: a query é dobrada antes (logo
 * "José" vira "jose") e cada letra vira uma classe com suas variantes (logo
 * "jose" casa "José"). Equivale ao `foldText(campo).includes(foldText(query))`
 * que o cliente aplica em {@link leadMatchesSearch}.
 *
 * O padrão NUNCA contém `.`, `,`, `(`, `)`, `*` ou `\`: são separadores da sintaxe
 * `or=(coluna.operador.valor,...)` do PostgREST — ou metacaracteres de regex — e
 * quebrariam o parse do servidor. Tudo fora de `[a-z0-9 ]` vira espaço.
 *
 * @returns o padrão, ou null quando não sobra nada pesquisável.
 */
export function buildAccentInsensitivePattern(query: string): string | null {
  const folded = foldText(query)
    .replace(/[^a-z0-9 ]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
  if (!folded) return null;

  return Array.from(folded)
    .map((ch) => {
      const variants = ACCENT_CLASSES[ch];
      return variants ? `[${variants}]` : ch;
    })
    .join("");
}

/**
 * Monta o valor do filtro `or=(...)` que a busca de contatos aplica sobre a
 * tabela `leads` embutida. Cobre os mesmos campos de {@link leadMatchesSearch}:
 * texto (accent-insensitive, via `imatch`) e telefone (substring de dígitos, via
 * `ilike`) — este último só entra quando a query tem algum dígito.
 *
 * @returns o filtro, ou null quando não há nada pesquisável (o chamador deve
 *          responder lista vazia sem ir ao banco).
 */
export function buildLeadSearchOrFilter(query: string): string | null {
  const pattern = buildAccentInsensitivePattern(query);
  if (!pattern) return null;

  const terms = LEAD_TEXT_COLUMNS.map((col) => `${col}.imatch.${pattern}`);

  const digits = query.replace(/\D/g, "");
  if (digits) terms.push(`phone.ilike.*${digits}*`);

  return terms.join(",");
}
