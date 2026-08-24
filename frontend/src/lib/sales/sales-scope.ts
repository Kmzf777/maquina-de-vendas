/**
 * Quem enxerga quais vendas em /painel-vendas.
 *
 * Funcao pura e separada da rota porque a regra tem duas consequencias que
 * precisam de teste: a comparacao de e-mail e insensivel a maiusculas (o seed
 * grava "Comercial2@..." com C maiusculo, e `eq` casaria zero linhas), e um
 * e-mail ausente ou com virgula LEVANTA em vez de devolver "sem escopo" —
 * devolver null ali abriria a base inteira por acidente.
 */
export interface SalesScopeUser {
  userId: string;
  email: string | undefined;
  role: string | undefined;
}

export class SalesScopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SalesScopeError";
  }
}

function emailValido(email: string | undefined): string {
  const limpo = (email ?? "").trim();
  if (!limpo) throw new SalesScopeError("usuario sem e-mail: escopo de vendas indeterminado");
  // A virgula separa termos no `or` do PostgREST. E-mail nao tem virgula; se
  // tiver, recusamos em vez de montar um filtro com um termo a mais.
  if (limpo.includes(",")) throw new SalesScopeError("e-mail invalido para escopo de vendas");
  return limpo;
}

function semEscopo(user: SalesScopeUser, enabled: boolean): boolean {
  return !enabled || user.role === "admin";
}

/**
 * Filtro `or` do PostgREST, ou `null` quando nao ha escopo (admin ou flag
 * desligada). O vendedor ve as vendas dele MAIS as importadas do ERP, que nao
 * tem dono e sao o material de conferencia dele.
 */
export function salesScopeFilter(user: SalesScopeUser, enabled: boolean): string | null {
  if (semEscopo(user, enabled)) return null;
  return `sold_by.ilike.${emailValido(user.email)},origin.eq.bling`;
}

/** Mesma regra, aplicada a uma linha ja carregada (rota /api/sales/[id]). */
export function podeVerVenda(
  sale: { sold_by: string | null; origin: string | null },
  user: SalesScopeUser,
  enabled: boolean,
): boolean {
  if (semEscopo(user, enabled)) return true;
  const email = emailValido(user.email).toLowerCase();
  if (sale.origin === "bling") return true;
  return (sale.sold_by ?? "").toLowerCase() === email;
}

/** Le a chave de rollback. Ligada por padrao: so "0"/"false" desligam. */
export function scopeAtivo(): boolean {
  const raw = (process.env.SALES_SCOPE_BY_SELLER ?? "").trim().toLowerCase();
  return raw !== "0" && raw !== "false";
}
