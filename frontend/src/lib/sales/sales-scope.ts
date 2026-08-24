/**
 * Quem enxerga quais vendas em /painel-vendas.
 *
 * Funcao pura e separada da rota porque a regra tem consequencias que
 * precisam de teste: a comparacao de e-mail e insensivel a maiusculas (o seed
 * grava "Comercial2@..." com C maiusculo, e `eq` casaria zero linhas); um
 * e-mail ausente ou com caractere reservado do PostgREST LEVANTA em vez de
 * devolver "sem escopo" — devolver null ali abriria a base inteira por
 * acidente; e o filtro `or=(col.op.valor,...)` e montado por concatenacao,
 * entao caracteres que o PostgREST trata como sintaxe ou curinga precisam ser
 * recusados antes de entrar no valor (ver RESERVADOS_POSTGREST abaixo).
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

// Caracteres que alteram a sintaxe ou a semantica do `or=(col.op.valor,...)` do
// PostgREST. Testado contra o servidor real em 24/08/2026:
//   - `.` FUNCIONA sem aspas e e obrigatorio permitir (todo e-mail tem um no
//     dominio); o parser separa nos dois primeiros pontos e o resto e valor.
//   - `*` e curinga de `ilike` (alias de `%`) e aspas NAO neutralizam — nao ha
//     escape, entao a unica defesa e recusar. Um `*` no e-mail transformaria a
//     comparacao exata numa busca por prefixo e ALARGARIA o escopo.
//   - `,` `(` `)` `:` sao separadores da sintaxe; recusados por precaucao.
//   - `%` e o curinga multi-caractere de ILIKE no proprio Postgres — mesmo
//     risco do `*`, que e so o alias do PostgREST para ele.
//   - `_` (curinga de UM caractere) fica PERMITIDO de proposito: recusa-lo
//     travaria fora do sistema qualquer usuario com underscore no e-mail, que
//     e comum, e o alargamento possivel e de um unico caractere numa posicao
//     fixa — para pegar outra pessoa, o e-mail dela teria que diferir
//     exatamente ali. O custo de recusar supera o risco de aceitar.
const RESERVADOS_POSTGREST = /[,()*:%]/;

function emailValido(email: string | undefined): string {
  const limpo = (email ?? "").trim();
  if (!limpo) throw new SalesScopeError("usuario sem e-mail: escopo de vendas indeterminado");
  if (RESERVADOS_POSTGREST.test(limpo)) {
    throw new SalesScopeError("e-mail invalido para escopo de vendas");
  }
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

/**
 * Qual vendedor entra na RPC `get_avg_repurchase_cycle_days`.
 *
 * A RPC agrega no banco e NAO passa pelo filtro `or` do escopo, entao o
 * parametro nao pode vir cru da URL: um vendedor pediria o e-mail de outro e
 * leria o ciclo de recompra alheio — vazamento de agregado, invisivel porque a
 * lista ao lado continuaria correta.
 *
 * Admin le o que pediu (inclusive `null` = a operacao toda). Vendedor le sempre
 * o proprio, filtrado ou nao — nunca o global. Com "Todos" selecionado isso
 * deixa o card mais estreito que os outros tres (que incluem as vendas
 * importadas do ERP, sem dono), e essa e a troca deliberada: preferimos o card
 * dizer menos a dizer respeito a outra pessoa.
 */
export function vendedorDaRecompra(
  user: SalesScopeUser | null,
  soldByDaUrl: string | null,
): string | null {
  if (!user || user.role === "admin") return soldByDaUrl || null;
  return emailValido(user.email);
}

/** Le a chave de rollback. Ligada por padrao: so "0"/"false" desligam. */
export function scopeAtivo(): boolean {
  const raw = (process.env.SALES_SCOPE_BY_SELLER ?? "").trim().toLowerCase();
  return raw !== "0" && raw !== "false";
}
