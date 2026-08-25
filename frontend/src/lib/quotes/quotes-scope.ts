/**
 * Quem enxerga quais orcamentos em /orcamento.
 *
 * A regra e a de /painel-vendas menos uma clausula: o vendedor ve `created_by =
 * o proprio e-mail`, e SO isso. Nao existe o `origin.eq.bling` que `sales` tem,
 * porque proposta criada direto no ERP nao e sincronizada (decisao 17 da spec) —
 * entao nao ha, e nao pode passar a haver, orcamento sem dono que seja material
 * legitimo de conferencia. A consequencia pratica esta documentada na migration:
 * orcamento gravado com `created_by` nulo fica invisivel para todo nao-admin, o
 * que e o comportamento correto para um fail-closed, e por isso a tela SEMPRE
 * manda o e-mail do vendedor no POST.
 *
 * A defesa contra os caracteres reservados do PostgREST NAO e reimplementada
 * aqui: `emailSeguroParaFiltro` vem de `lib/sales/sales-scope.ts`, onde a lista
 * de caracteres e o motivo de cada um estao documentados e testados. Duas copias
 * da mesma validacao apodrecem — a proxima correcao entraria so numa delas.
 */
import {
  emailSeguroParaFiltro,
  scopeAtivo,
  SalesScopeError,
  type SalesScopeUser,
} from "@/lib/sales/sales-scope";

/**
 * O usuario e a excecao sao os MESMOS tipos do escopo de vendas, reexportados em
 * vez de clonados.
 *
 * Nao e preguica de nomenclatura: `resolverEscopoDeOrcamentos` captura
 * `SalesScopeError` para transformar em 401, e um `QuotesScopeError` separado
 * significaria que `emailSeguroParaFiltro` — que e compartilhada — teria que
 * saber de qual dominio ela foi chamada para escolher qual classe levantar. O
 * `catch` das duas rotas casa na mesma classe porque o defeito e o mesmo: o
 * usuario logado nao tem e-mail utilizavel como filtro.
 */
export { SalesScopeError as QuotesScopeError, scopeAtivo };
export type QuotesScopeUser = SalesScopeUser;

function semEscopo(user: QuotesScopeUser, enabled: boolean): boolean {
  return !enabled || user.role === "admin";
}

/**
 * Filtro `or` do PostgREST para `quotes`, ou `null` quando nao ha escopo (admin
 * ou flag de rollback desligada).
 *
 * Continua sendo um `or` de um termo so — e nao um `.eq()` — de proposito.
 * Primeiro porque `ilike` e o que torna a comparacao insensivel a maiusculas, e
 * o e-mail chega com a grafia que a conta do Supabase tem (o painel de vendas
 * ja tropecou nisso com "Comercial2@..."); depois porque as rotas combinam este
 * filtro com os da query string via AND, entao um filtro de vendedor vindo da
 * URL so consegue RESTRINGIR o conjunto ja permitido, nunca alarga-lo.
 */
export function quotesScopeFilter(user: QuotesScopeUser, enabled: boolean): string | null {
  if (semEscopo(user, enabled)) return null;
  return `created_by.ilike.${emailSeguroParaFiltro(user.email)}`;
}

/**
 * Mesma regra, aplicada a UMA linha ja carregada — as rotas de /api/quotes/[id].
 *
 * O filtro `or` protege a listagem, mas nao alcanca as rotas que recebem o id na
 * URL: ler, editar, mudar situacao, converter e baixar o PDF de um orcamento
 * qualquer eram, sem isto, operacoes livres para qualquer usuario autenticado
 * que tivesse o UUID. Nao e enumeravel, mas "nao e enumeravel" nao e controle de
 * acesso — e `/api/sales/[id]` ja tem o gemeo disto (`podeVerVenda`), entao a
 * ausencia aqui era assimetria, nao decisao.
 *
 * Vale para o PDF em particular: ele e o documento comercial com preco negociado
 * e margem embutida. Vazar o de outro vendedor e pior que vazar a linha da
 * tabela.
 *
 * Comparacao em caixa baixa pelo mesmo motivo do `ilike` do filtro: o e-mail
 * gravado tem a grafia da conta do Supabase, que nem sempre e minuscula.
 * Orcamento sem `created_by` NAO e visivel para nao-admin — fail-closed, e o
 * inverso de `sales`, onde venda sem dono e material legitimo de conferencia.
 */
export function podeVerOrcamento(
  quote: { created_by: string | null },
  user: QuotesScopeUser,
  enabled: boolean,
): boolean {
  if (semEscopo(user, enabled)) return true;
  const email = emailSeguroParaFiltro(user.email).toLowerCase();
  return (quote.created_by ?? "").toLowerCase() === email;
}
