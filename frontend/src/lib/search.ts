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
  email?: string | null;
  cnpj?: string | null;
}

/**
 * Termos da busca: texto dobrado (sem acento, minúsculo), quebrado em tudo que não é
 * letra/dígito. "Angelucci, Hiágo" → ["angelucci", "hiago"]. É a MESMA quebra que o
 * servidor usa em {@link buildLeadSearchOrFilter}.
 */
export function searchTokens(query: string): string[] {
  return foldText(query)
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
}

const digitsOf = (value: string | null | undefined): string => (value ?? "").replace(/\D/g, "");

/**
 * True quando a busca casa com o lead:
 *  1. os dígitos da busca inteira aparecem no telefone ou no CNPJ (com ou sem máscara
 *     dos dois lados — "(34) 99999-8888", "25.139.264/0001-51"); ou
 *  2. TODOS os termos aparecem, em qualquer ordem e em qualquer campo de texto
 *     (nome, empresa, razão social, fantasia, e-mail) — termo só de dígitos também
 *     vale no telefone/CNPJ. "angelucci hiago" acha "Hiago Angelucci".
 * É superconjunto da regra antiga (frase contígua). Busca vazia casa tudo.
 */
export function leadMatchesSearch(query: string, lead: LeadSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const phoneDigits = digitsOf(lead.phone);
  const cnpjDigits = digitsOf(lead.cnpj);
  const qDigits = digitsOf(raw);
  if (qDigits && (phoneDigits.includes(qDigits) || cnpjDigits.includes(qDigits))) return true;

  const tokens = searchTokens(raw);
  if (tokens.length === 0) return false;

  const text = [lead.name, lead.company, lead.razao_social, lead.nome_fantasia, lead.email]
    .filter((field): field is string => field != null)
    .map(foldText)
    .join("\n");

  return tokens.every(
    (token) =>
      text.includes(token) ||
      (/^\d+$/.test(token) && (phoneDigits.includes(token) || cnpjDigits.includes(token))),
  );
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
const LEAD_TEXT_COLUMNS = ["name", "company", "razao_social", "nome_fantasia", "email"] as const;

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
 * Padrão POSIX que casa a sequência de dígitos tolerando até dois separadores entre
 * eles — "25139264000151" casa "25.139.264/0001-51" e "34988887777" casa
 * "(34) 98888-7777". Só usa `[^0-9]?`: nada que quebre o parser do `or=()`.
 */
export function buildDigitsPattern(digits: string): string {
  return Array.from(digits).join("[^0-9]?[^0-9]?");
}

/** Termos `coluna.op.valor` de UM token: texto em todas as colunas, dígitos em telefone/CNPJ. */
function tokenTerms(token: string): string[] {
  const pattern = buildAccentInsensitivePattern(token) ?? token;
  const terms: string[] = LEAD_TEXT_COLUMNS.map((col) => `${col}.imatch.${pattern}`);
  if (/^\d+$/.test(token)) {
    const d = buildDigitsPattern(token);
    terms.push(`phone.imatch.${d}`, `cnpj.imatch.${d}`);
  }
  return terms;
}

/**
 * Monta o valor do filtro `or=(...)` que a busca de contatos aplica sobre a tabela
 * `leads` embutida — a mesma regra de {@link leadMatchesSearch}:
 *  - dígitos da busca inteira no telefone/CNPJ (tolerando máscara, via `imatch`);
 *  - OU todos os termos: `and(or(<termo1 em cada coluna>),or(<termo2 ...>))`.
 * Uma busca de um termo só fica plana (`col.imatch.x,...`).
 *
 * @returns o filtro, ou null quando não há nada pesquisável (o chamador deve
 *          responder lista vazia sem ir ao banco).
 */
export function buildLeadSearchOrFilter(query: string): string | null {
  const tokens = searchTokens(query);
  if (tokens.length === 0) return null;

  const terms: string[] = [];
  const digits = query.replace(/\D/g, "");
  const singleDigitToken = tokens.length === 1 && tokens[0] === digits;
  if (digits && !singleDigitToken) {
    const d = buildDigitsPattern(digits);
    terms.push(`phone.imatch.${d}`, `cnpj.imatch.${d}`);
  }

  if (tokens.length === 1) {
    terms.push(...tokenTerms(tokens[0]));
  } else {
    terms.push(`and(${tokens.map((t) => `or(${tokenTerms(t).join(",")})`).join(",")})`);
  }
  return terms.join(",");
}
